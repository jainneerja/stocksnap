"""Photo -> barcode / known item / AI draft.

Split into two calls on purpose:
  POST /api/scan      fast (<1s): save photo, read barcode, find look-alike items
  POST /api/photos    save an extra photo only (e.g. a close-up of the size tag)
  POST /api/describe  slow (seconds on CPU): local vision model drafts the listing,
                      reading size/price from the optional tag photo
The UI shows scan results immediately and fills in the AI draft when it arrives.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db import current_shop, get_session, shop_settings
from ..models import Item, ItemRead
from ..services.barcode import read_barcode
from ..services.images import InvalidImage, load_image, resolve_image, save_image
from ..services.vision import VisionUnavailable, seller_context

router = APIRouter(prefix="/api", tags=["scan"])

MAX_UPLOAD = 15 * 1024 * 1024


class ScanMatch(BaseModel):
    item: ItemRead
    score: float


class ScanResult(BaseModel):
    image_path: str
    barcode: Optional[str] = None
    barcode_format: Optional[str] = None
    barcode_item: Optional[ItemRead] = None  # exact match on barcode or SKU
    matches: list[ScanMatch] = []  # visual look-alikes from your catalogue


class DescribeRequest(BaseModel):
    image_path: str
    tag_image_path: Optional[str] = None  # close-up of label / hang tag
    hint: str = Field(default="", max_length=300)  # seller's own words: "what is it?"


class PhotoSaved(BaseModel):
    image_path: str


async def _read_upload(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is too large (max 15 MB)")
    try:
        return load_image(data)
    except InvalidImage as exc:
        raise HTTPException(400, str(exc))


@router.post("/scan", response_model=ScanResult)
async def scan(
    request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    img = await _read_upload(file)
    settings = shop_settings(request)
    name = save_image(img, settings.images_dir, settings.max_image_px)
    result = ScanResult(image_path=name)

    hit = read_barcode(img)
    if hit:
        result.barcode, result.barcode_format = hit.text, hit.format
        item = session.exec(
            select(Item).where((Item.barcode == hit.text) | (Item.sku == hit.text.upper()))
        ).first()
        if item:
            result.barcode_item = ItemRead.model_validate(item)

    for m in request.app.state.ai.find_similar(session, img):
        item = session.get(Item, m.item_id)
        if item:
            result.matches.append(ScanMatch(item=ItemRead.model_validate(item), score=m.score))
    return result


@router.post("/photos", response_model=PhotoSaved)
async def save_photo(request: Request, file: UploadFile = File(...)):
    img = await _read_upload(file)
    settings = shop_settings(request)
    # Keep tag close-ups sharper so small print stays legible.
    return PhotoSaved(image_path=save_image(img, settings.images_dir, max(settings.max_image_px, 1600)))


@router.post("/describe")
def describe(body: DescribeRequest, request: Request):
    images_dir = shop_settings(request).images_dir
    try:
        paths = [resolve_image(images_dir, body.image_path)]
        if body.tag_image_path:
            paths.append(resolve_image(images_dir, body.tag_image_path))
    except FileNotFoundError:
        raise HTTPException(404, "Image not found")
    try:
        seller = seller_context(current_shop(request).info.ai_context, body.hint)
        images = [load_image(p.read_bytes()) for p in paths]
        draft = request.app.state.ai.vision.describe(images, seller=seller)
    except VisionUnavailable:
        # Graceful fallback: the user just types the details in.
        raise HTTPException(
            503, "The local AI model isn't available right now - you can fill in the details yourself."
        )
    return draft.to_dict()
