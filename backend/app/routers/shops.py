"""Shops API: list, create, switch, settings, logo."""

from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from typing import Optional

from ..db import SHOP_COOKIE, current_shop
from ..services.images import resolve_image
from ..services.shops import SHOP_KINDS, ShopInfo, suggest_prefix

router = APIRouter(tags=["shops"])

TEN_YEARS = 10 * 365 * 24 * 3600


class ShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "other"
    sku_prefix: Optional[str] = None
    low_stock_default: int = Field(default=2, ge=0, le=1000)
    ai_context: str = Field(default="", max_length=400)


class ShopUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    kind: Optional[str] = None
    sku_prefix: Optional[str] = None
    low_stock_default: Optional[int] = Field(default=None, ge=0, le=1000)
    ai_context: Optional[str] = Field(default=None, max_length=400)


class ShopList(BaseModel):
    shops: list[ShopInfo]
    current: Optional[str]
    kinds: list[str]


def _select(response: Response, slug: str) -> None:
    response.set_cookie(SHOP_COOKIE, slug, max_age=TEN_YEARS, samesite="lax", httponly=True)


def _need(request: Request, slug: str) -> ShopInfo:
    info = request.app.state.shops.get(slug)
    if info is None:
        raise HTTPException(404, "Shop not found")
    return info


@router.get("/api/shops", response_model=ShopList)
def list_shops(request: Request):
    reg = request.app.state.shops
    shops = reg.list()
    current = None
    if shops:
        current = current_shop(request).info.slug
    return ShopList(shops=shops, current=current, kinds=list(SHOP_KINDS))


@router.get("/api/shops/suggest-prefix")
def prefix_for(name: str = ""):
    return {"sku_prefix": suggest_prefix(name) if name.strip() else ""}


@router.post("/api/shops", response_model=ShopInfo, status_code=201)
def create_shop(data: ShopCreate, request: Request, response: Response):
    info = request.app.state.shops.create(data.name, data.kind, data.sku_prefix, data.low_stock_default,
                                         data.ai_context)
    request.app.state.shops.context(info)  # creates the database now, not on first use
    _select(response, info.slug)
    return info


@router.post("/api/shops/{slug}/select", response_model=ShopInfo)
def select_shop(slug: str, request: Request, response: Response):
    info = _need(request, slug)
    _select(response, slug)
    return info


@router.patch("/api/shops/{slug}", response_model=ShopInfo)
def update_shop(slug: str, data: ShopUpdate, request: Request):
    _need(request, slug)
    return request.app.state.shops.update(slug, **data.model_dump(exclude_unset=True))


@router.post("/api/shops/{slug}/logo", response_model=ShopInfo)
async def upload_logo(slug: str, request: Request, file: UploadFile = File(...)):
    _need(request, slug)
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Logo is too large (max 10 MB)")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGBA")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Could not read that image. Try a PNG or JPG.")
    img.thumbnail((512, 512))
    img.save(request.app.state.shops.logo_path(slug), "PNG")
    return request.app.state.shops.update(slug, has_logo=True)


@router.delete("/api/shops/{slug}/logo", response_model=ShopInfo)
def remove_logo(slug: str, request: Request):
    _need(request, slug)
    path = request.app.state.shops.logo_path(slug)
    if path.is_file():
        path.unlink()
    return request.app.state.shops.update(slug, has_logo=False)


@router.get("/api/shops/{slug}/logo", include_in_schema=False)
def get_logo(slug: str, request: Request):
    _need(request, slug)
    path = request.app.state.shops.logo_path(slug)
    if not path.is_file():
        raise HTTPException(404, "No logo")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/images/{name}", include_in_schema=False)
def shop_image(name: str, request: Request):
    """Photos of the current shop (chosen by cookie, like every other request)."""
    try:
        path = resolve_image(current_shop(request).settings.images_dir, name)
    except FileNotFoundError:
        raise HTTPException(404, "Image not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})
