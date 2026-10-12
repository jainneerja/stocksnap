"""Scene templates and listing photos.

  /api/scenes                 your scene templates (upload, adjust, try, delete)
  /api/listing-photos         put saved products into scenes in one go (e.g. after
                              a bulk add) and download them as one ZIP, named by SKU
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import current_shop
from ..models import Item
from ..services.imagelab import _solid, compose, load_image_any
from ..services.images import resolve_image
from ..services.scenes import SceneStore, SceneTemplate, Stroke

log = logging.getLogger(__name__)
router = APIRouter(tags=["scenes"])
MAX_UPLOAD = 25 * 1024 * 1024


def _store(request: Request) -> SceneStore:
    return SceneStore(current_shop(request).settings.data_dir / "scenes")


def _get(store: SceneStore, scene_id: str) -> SceneTemplate:
    try:
        return store.get(scene_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Scene not found")


async def _image(file: UploadFile) -> Image.Image:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image is too large (max 25 MB)")
    try:
        return load_image_any(data)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Could not read that image. Try a JPG or PNG.")


def _jpeg(img: Image.Image) -> Response:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ scenes


class StrokeIn(BaseModel):
    points: list[list[float]] = Field(max_length=2000)
    r: float = Field(default=0.02, gt=0, le=0.2)


class SceneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    cx: Optional[float] = Field(default=None, ge=0, le=1)
    top: Optional[float] = Field(default=None, ge=0, le=1)
    bottom: Optional[float] = Field(default=None, ge=0, le=1)
    rx: Optional[float] = Field(default=None, gt=0, le=1)
    tilt: Optional[float] = Field(default=None, ge=0.15, le=0.5)
    top_box: Optional[list[float]] = None  # [] = no top piece
    keep: Optional[list[StrokeIn]] = Field(default=None, max_length=200)
    remove: Optional[list[StrokeIn]] = Field(default=None, max_length=200)
    keep_outlines: Optional[list[list[list[float]]]] = Field(default=None, max_length=50)
    remove_outlines: Optional[list[list[list[float]]]] = Field(default=None, max_length=50)
    shading: Optional[float] = Field(default=None, ge=0, le=1)
    shadow: Optional[float] = Field(default=None, ge=0, le=1)
    scale: Optional[float] = Field(default=None, ge=0.5, le=1.2)
    empty_base: Optional[bool] = None


@router.get("/api/scenes")
def list_scenes(request: Request):
    return [t.to_dict() for t in _store(request).list()]


@router.post("/api/scenes", status_code=201)
async def create_scene(request: Request, file: UploadFile = File(...), name: str = Form("")):
    store = _store(request)
    t = store.create(await _image(file), name or "Scene")
    return t.to_dict()


@router.get("/api/scenes/{scene_id}")
def get_scene(scene_id: str, request: Request):
    return _get(_store(request), scene_id).to_dict()


@router.put("/api/scenes/{scene_id}")
def update_scene(scene_id: str, body: SceneUpdate, request: Request):
    store = _store(request)
    t = _get(store, scene_id)
    changes = body.model_dump(exclude_unset=True)
    for k in ("keep", "remove"):
        if k in changes:
            changes[k] = [Stroke(points=s["points"], r=s["r"]) for s in changes[k]]
    if "top_box" in changes:
        box = changes["top_box"]
        if box and (len(box) != 4 or not all(0 <= v <= 1 for v in box) or box[0] >= box[2] or box[1] >= box[3]):
            raise HTTPException(400, "Top piece box must be [x0, y0, x1, y1] between 0 and 1")
        changes["top_box"] = box or None
    for k, v in changes.items():
        setattr(t, k, v)
    if t.bottom - t.top < 0.05:
        raise HTTPException(400, "The product area is too small")
    return store.save(t).to_dict()


class AutoSetup(BaseModel):
    product: str = Field(default="dress", min_length=1, max_length=60)
    keep: str = Field(default="hand, arm, necklace, anything held in a hand", max_length=300)
    top_piece: bool = True  # the product has a top part on the chest (bodice)


@router.post("/api/scenes/{scene_id}/auto")
def auto_setup(scene_id: str, body: AutoSetup, request: Request):
    """'Find them for me': the local vision model finds the product, its top
    part, the face and whatever should stay on top; the app turns that into the
    oval, the top-piece box and exact outlines."""
    import cv2

    from ..services.scenes import apply_found
    from ..services.vision import VisionUnavailable

    store = _store(request)
    t = _get(store, scene_id)
    product = body.product.strip().lower()
    keep = [k.strip().lower() for k in re.split(r"[,;\n]", body.keep) if k.strip()][:8]
    top_label = f"top part of the {product} on the chest" if body.top_piece else None
    labels = [product, *([top_label] if top_label else []), "face", *keep]
    vision = request.app.state.ai.vision
    if not hasattr(vision, "locate"):
        raise HTTPException(503, "This AI model can't find things in pictures.")
    d = store.dir(scene_id)
    start = time.time()
    try:
        found = vision.locate(Image.open(d / "scene.jpg"), labels)
    except VisionUnavailable:
        raise HTTPException(503, "The local AI isn't running. Start Ollama, or set the scene up by hand.")
    scene = cv2.imread(str(d / "scene.jpg"))
    if not body.top_piece:
        t.top_box = None
        keep = [*keep, "face"]
    notes = apply_found(t, scene, found, product, top_label, keep)
    if not found:
        raw = (getattr(vision, "last_locate_raw", "") or "").strip().replace("\n", " ")
        notes.append("The AI's reply couldn't be read" + (f": \"{raw[:300]}\"" if raw else " (it was empty)."))
    t.keep, t.remove = [], []
    store.save(t)
    return {"scene": t.to_dict(), "notes": notes, "seconds": round(time.time() - start, 1),
            "found": {k: len(v) for k, v in found.items()}}


@router.delete("/api/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: str, request: Request):
    store = _store(request)
    _get(store, scene_id)
    store.delete(scene_id)


@router.get("/api/scenes/{scene_id}/files/{name}", include_in_schema=False)
def scene_file(scene_id: str, name: str, request: Request):
    try:
        path = _store(request).file(scene_id, name)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "File not found")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.post("/api/scenes/{scene_id}/try")
async def try_scene(scene_id: str, request: Request, file: Optional[UploadFile] = File(None),
                    item_id: Optional[int] = Form(None)):
    """Quick preview: a product (uploaded photo or a saved item) in this scene."""
    store = _store(request)
    _get(store, scene_id)
    if file is not None:
        img = await _image(file)
    elif item_id is not None:
        img = _item_image(request, item_id)
    else:
        raise HTTPException(400, "Send a product photo or an item")
    cut = request.app.state.lab.cutter.cut(img)
    return _jpeg(store.render(scene_id, img, cut))


def _item_image(request: Request, item_id: int) -> Image.Image:
    shop = current_shop(request)
    with Session(shop.engine) as session:
        item = session.get(Item, item_id)
        if not item or not item.image_path:
            raise HTTPException(404, "That item has no photo")
        try:
            return Image.open(resolve_image(shop.settings.images_dir, item.image_path)).convert("RGB")
        except FileNotFoundError:
            raise HTTPException(404, "That item's photo is missing")


# ------------------------------------------------------------- listing photos


class ListingItem(BaseModel):
    item_id: int
    scene_ids: list[str] = Field(default_factory=list, max_length=6)


class ListingRequest(BaseModel):
    items: list[ListingItem] = Field(min_length=1, max_length=500)
    white: bool = True  # also a plain white main image (marketplace main photo)


def _listing_root(request: Request) -> Path:
    root = current_shop(request).settings.data_dir / "listing"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job_dir(root: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", job_id or "") or not (root / job_id / "job.json").is_file():
        raise HTTPException(404, "Job not found")
    return root / job_id


def _write(d: Path, job: dict) -> None:
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    os.replace(tmp, d / "job.json")


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:40] or "item"


@router.post("/api/listing-photos", status_code=201)
def create_listing_job(body: ListingRequest, request: Request, tasks: BackgroundTasks):
    shop = current_shop(request)
    store = _store(request)
    scene_names = {t.id: t.name for t in store.list()}
    rows = []
    with Session(shop.engine) as session:
        for it in body.items:
            item = session.get(Item, it.item_id)
            if not item:
                raise HTTPException(404, f"Item {it.item_id} not found")
            bad = [s for s in it.scene_ids if s not in scene_names]
            if bad:
                raise HTTPException(404, "Scene not found")
            rows.append({"item_id": item.id, "sku": item.sku, "name": item.name, "image_path": item.image_path,
                         "scene_ids": it.scene_ids})
    if not body.white and not any(r["scene_ids"] for r in rows):
        raise HTTPException(400, "Pick at least one scene or the white main image")
    root = _listing_root(request)
    job_id = uuid.uuid4().hex[:12]
    d = root / job_id
    (d / "out").mkdir(parents=True)
    job = {"id": job_id, "status": "queued", "created": time.time(), "white": body.white, "items": rows,
           "scene_names": scene_names, "done": 0, "total": len(rows), "outputs": [], "notes": [], "total_s": 0}
    _write(d, job)
    tasks.add_task(_run_listing, request.app.state.lab.cutter, store, shop.settings.images_dir, d)
    return job


def _run_listing(cutter, store: SceneStore, images_dir: Path, d: Path) -> None:
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    start = time.time()
    job["status"] = "running"
    for row in job["items"]:
        try:
            if not row["image_path"]:
                job["notes"].append(f"{row['sku']}: no photo, skipped")
                continue
            img = Image.open(resolve_image(images_dir, row["image_path"])).convert("RGB")
            cut = cutter.cut(img)
            n = 0
            if job["white"]:
                name = f"{_safe(row['sku'])}.{n:02d}-white.jpg"
                compose(cut, _solid((255, 255, 255)), 0.85, 0.18).convert("RGB").save(d / "out" / name, "JPEG", quality=90)
                job["outputs"].append({"item_id": row["item_id"], "sku": row["sku"], "file": name, "label": "Main (white)"})
                n += 1
            for sid in row["scene_ids"]:
                name = f"{_safe(row['sku'])}.{n:02d}-{sid}.jpg"
                store.render(sid, img, cut).save(d / "out" / name, "JPEG", quality=90)
                job["outputs"].append({"item_id": row["item_id"], "sku": row["sku"], "file": name,
                                       "label": job["scene_names"].get(sid, "Scene")})
                n += 1
        except Exception as exc:  # noqa: BLE001 - one bad photo shouldn't stop the batch
            log.exception("listing photo failed")
            job["notes"].append(f"{row['sku']}: {exc}")
        job["done"] += 1
        _write(d, job)
    job["status"], job["total_s"] = "done", round(time.time() - start, 1)
    _write(d, job)


@router.get("/api/listing-photos/{job_id}")
def get_listing_job(job_id: str, request: Request):
    d = _job_dir(_listing_root(request), job_id)
    return json.loads((d / "job.json").read_text(encoding="utf-8"))


@router.get("/api/listing-photos/{job_id}/files/{name}", include_in_schema=False)
def listing_file(job_id: str, name: str, request: Request):
    d = _job_dir(_listing_root(request), job_id)
    path = d / "out" / name
    if "/" in name or "\\" in name or ".." in name or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@router.get("/api/listing-photos/{job_id}/zip")
def listing_zip(job_id: str, request: Request):
    """One ZIP for the whole batch, Amazon-style names: SKU.MAIN.jpg, SKU.PT01.jpg ..."""
    d = _job_dir(_listing_root(request), job_id)
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    buf = io.BytesIO()
    counters: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for o in job["outputs"]:
            sku = _safe(o["sku"])
            i = counters.get(sku, 0)
            counters[sku] = i + 1
            zf.write(d / "out" / o["file"], f"{sku}/{sku}.{'MAIN' if i == 0 else f'PT{i:02d}'}.jpg")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=listing-photos-{job_id[:6]}.zip"})
