"""Product catalogues: pick a folder of product photos, get a PDF catalogue.

  POST /api/catalogues                 photos (one per product) + title + "what are these?"
  GET  /api/catalogues                 recent catalogues
  GET  /api/catalogues/{id}            names, descriptions, prices (written in the background)
  PUT  /api/catalogues/{id}            the seller's edits (names, prices, codes, which to include)
  GET  /api/catalogues/{id}/pdf        the catalogue as a PDF
  GET  /api/catalogues/{id}/photos/{f} a product photo
  DELETE /api/catalogues/{id}
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from ..db import current_shop
from ..services.catalogue import build_pdf, name_from_file
from ..services.imagelab import _solid, compose
from ..services.images import load_image
from ..services.listing import Known, describe_item
from ..services.vision import VisionUnavailable, seller_context

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/catalogues", tags=["catalogues"])

MAX_FILES = 300
MAX_BYTES = 25 * 1024 * 1024
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp"}
_KIND_ITEM = {"clothing": "outfit", "jewellery": "piece", "soap": "soap", "candle": "candle"}


def _root(request: Request) -> Path:
    root = current_shop(request).settings.data_dir / "catalogues"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dir(request: Request, cat_id: str) -> Path:
    d = _root(request) / cat_id
    if not re.fullmatch(r"[0-9a-f]{12}", cat_id or "") or not (d / "catalogue.json").is_file():
        raise HTTPException(404, "Catalogue not found")
    return d


def _read(d: Path) -> dict:
    return json.loads((d / "catalogue.json").read_text(encoding="utf-8"))


def _write(d: Path, cat: dict) -> None:
    tmp = d / "catalogue.json.tmp"
    tmp.write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / "catalogue.json")


def _natural(name: str):
    """'dress10' after 'dress9', like a file browser."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


@router.post("", status_code=201)
async def create_catalogue(
    request: Request,
    tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    title: str = Form(""),
    hint: str = Form(""),
    clean_background: bool = Form(False),
    describe: bool = Form(True),
):
    shop = current_shop(request)
    photos = [f for f in files if Path(f.filename or "").suffix.lower() in IMAGE_EXT or
              (f.content_type or "").startswith("image/")]
    if not photos:
        raise HTTPException(400, "No photos found. Pick a folder with JPG or PNG photos.")
    if len(photos) > MAX_FILES:
        raise HTTPException(400, f"Up to {MAX_FILES} photos at a time.")
    photos.sort(key=lambda f: _natural(Path(f.filename or "").name))

    cat_id = uuid.uuid4().hex[:12]
    d = _root(request) / cat_id
    (d / "photos").mkdir(parents=True)
    prefix = (shop.info.sku_prefix or "CAT").upper()
    items, skipped = [], []
    for n, f in enumerate(photos, start=1):
        fname = Path(f.filename or f"photo{n}").name
        data = await f.read()
        if len(data) > MAX_BYTES:
            skipped.append(f"{fname}: too large")
            continue
        try:
            img = load_image(data)
        except Exception:  # noqa: BLE001
            skipped.append(f"{fname}: not a photo the app can read")
            continue
        img.thumbnail((1600, 1600))
        photo = f"{len(items) + 1:03d}.jpg"
        img.save(d / "photos" / photo, "JPEG", quality=90)
        items.append({"id": len(items) + 1, "file": fname, "photo": photo, "original": photo,
                      "name": name_from_file(fname), "description": "", "price": "",
                      "code": f"{prefix}-{len(items) + 1:03d}", "include": True, "status": "queued"})
    if not items:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "None of those files could be read as photos.")
    cat = {"id": cat_id, "created": time.time(), "title": title.strip() or f"{shop.info.name} catalogue",
           "subtitle": "", "columns": 2, "hint": hint.strip(), "clean_background": clean_background,
           "describe": describe, "status": "running", "done": 0, "total": len(items),
           "notes": skipped, "mode": "", "items": items}
    _write(d, cat)
    tasks.add_task(_prepare, request.app.state.ai.vision, request.app.state.lab.cutter,
                   request.app.state.shops.style(shop.info), shop.info, d)
    return cat


def _prepare(vision, cutter, style, info, d: Path) -> None:
    """Background: names/descriptions (and optional white cut-outs) for each photo.
    The seller may already be typing prices meanwhile, so each result is merged
    into the latest saved file and never overwrites the seller's own edits."""
    from ..services.listing import ShopStyle

    cat = _read(d)
    hint = cat.get("hint", "")
    seller = seller_context(info.ai_context, hint)
    fallback = _KIND_ITEM.get(info.kind, "item")
    modes = set()
    for item in cat["items"]:
        res: dict = {"status": "ready"}
        note = ""
        try:
            img = Image.open(d / "photos" / item["original"]).convert("RGB")
            if cat.get("clean_background"):
                white = f"{item['id']:03d}-white.jpg"
                compose(cutter.cut(img), _solid((255, 255, 255)), 0.86, 0.15).convert("RGB").save(
                    d / "photos" / white, "JPEG", quality=90)
                res["photo"] = white
            name = item["name"]
            if cat.get("describe", True):
                try:
                    draft, mode = describe_item(vision, style, [img], Known(type=hint), seller=seller,
                                                fallback_type=fallback)
                except VisionUnavailable:  # "detailed" mode with the AI off: instant instead
                    instant = ShopStyle(name=style.name, kind=style.kind, mode="instant",
                                        name_template=style.name_template, desc_template=style.desc_template)
                    draft, mode = describe_item(vision, instant, [img], Known(type=hint), fallback_type=fallback)
                modes.add(mode)
                name = name or draft.name  # a name the seller gave the file always wins
                res["description"] = draft.description
            res["name"] = name or f"{(hint or fallback).capitalize()} {item['id']}"
        except Exception as exc:  # noqa: BLE001 - one bad photo shouldn't stop the rest
            log.exception("catalogue photo failed")
            res = {"status": "failed"}
            note = f"{item['file']}: {exc}"
        latest = _read(d)
        for it in latest["items"]:
            if it["id"] == item["id"]:
                for k, v in res.items():
                    if k in ("name", "description") and it.get(f"{k}_edited"):
                        continue
                    it[k] = v
        latest["done"] += 1
        if note:
            latest["notes"].append(note)
        _write(d, latest)
    latest = _read(d)
    latest["status"], latest["mode"] = "done", ", ".join(sorted(modes))
    _write(d, latest)


class ItemEdit(BaseModel):
    id: int
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=600)
    price: Optional[str] = Field(default=None, max_length=30)
    code: Optional[str] = Field(default=None, max_length=30)
    include: Optional[bool] = None


class CatalogueEdit(BaseModel):
    title: Optional[str] = Field(default=None, max_length=100)
    subtitle: Optional[str] = Field(default=None, max_length=200)
    columns: Optional[int] = Field(default=None, ge=2, le=3)
    items: list[ItemEdit] = Field(default_factory=list, max_length=MAX_FILES)


@router.get("")
def list_catalogues(request: Request):
    out = []
    for d in sorted(_root(request).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            c = _read(d)
        except (OSError, ValueError):
            continue
        out.append({"id": c["id"], "title": c["title"], "created": c["created"], "total": c["total"],
                    "status": c["status"], "cover": c["items"][0]["photo"] if c["items"] else None})
    return out[:30]


@router.get("/{cat_id}")
def get_catalogue(cat_id: str, request: Request):
    return _read(_dir(request, cat_id))


@router.put("/{cat_id}")
def edit_catalogue(cat_id: str, body: CatalogueEdit, request: Request):
    d = _dir(request, cat_id)
    cat = _read(d)
    for k in ("title", "subtitle", "columns"):
        v = getattr(body, k)
        if v is not None:
            cat[k] = v.strip() if isinstance(v, str) else v
    by_id = {it["id"]: it for it in cat["items"]}
    for e in body.items:
        it = by_id.get(e.id)
        if it is None:
            raise HTTPException(404, f"Product {e.id} not in this catalogue")
        for k, v in e.model_dump(exclude_unset=True, exclude={"id"}).items():
            v = v.strip() if isinstance(v, str) else v
            if k in ("name", "description") and v != it.get(k):
                it[f"{k}_edited"] = True  # the AI, still working, won't overwrite it
            it[k] = v
    _write(d, cat)
    return cat


@router.get("/{cat_id}/pdf")
def catalogue_pdf(cat_id: str, request: Request):
    d = _dir(request, cat_id)
    cat = _read(d)
    shop = current_shop(request)
    if not any(it.get("include", True) and it["status"] != "failed" for it in cat["items"]):
        raise HTTPException(400, "No products selected for the catalogue.")
    logo = request.app.state.shops.logo_path(shop.info.slug) if shop.info.has_logo else None
    pdf = build_pdf(cat, d / "photos", shop.info.name, logo)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", cat["title"]).strip("-")[:50] or "catalogue"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})


@router.get("/{cat_id}/photos/{name}", include_in_schema=False)
def catalogue_photo(cat_id: str, name: str, request: Request):
    d = _dir(request, cat_id)
    path = d / "photos" / name
    if not re.fullmatch(r"[0-9]{3}(-white)?\.jpg", name) or not path.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@router.delete("/{cat_id}", status_code=204)
def delete_catalogue(cat_id: str, request: Request):
    shutil.rmtree(_dir(request, cat_id), ignore_errors=True)
