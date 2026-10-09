"""Bulk intake API. See services/bulk.py for the flow."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db import current_shop, get_session, shop_settings
from ..models import Batch, BatchGroup, BatchPhoto, Detection, Item, ItemRead
from ..services import bulk
from ..services.images import InvalidImage, load_image
from ..services.presets import PRESETS
from .items import _auto_sku

router = APIRouter(prefix="/api", tags=["bulk intake"])

MAX_UPLOAD = 25 * 1024 * 1024


class BatchCreate(BaseModel):
    preset: str
    answers: dict[str, str] = {}


class DetectionOut(BaseModel):
    id: int
    number: int
    bbox: list[int]
    include: bool
    group_id: int


class PhotoOut(BaseModel):
    id: int
    image_path: str
    width: int
    height: int
    detections: list[DetectionOut]


class ItemRef(BaseModel):
    id: int
    sku: str
    name: str
    size: str
    quantity: int
    price_cents: int


class GroupOut(BaseModel):
    id: int
    status: str
    name: str
    description: str
    category: str
    tags: str
    color: str
    size: str
    material: str
    brand: str
    cost_cents: int
    price_cents: int
    include: bool
    count: int
    count_override: Optional[int]
    numbers: list[int]
    crops: list[str]
    existing_item: Optional[ItemRef] = None
    item: Optional[ItemRef] = None


class BatchOut(BaseModel):
    id: int
    preset: str
    preset_label: str
    mode: str
    answers: dict[str, str]
    status: str
    describing: bool
    created_at: datetime
    photos: list[PhotoOut]
    groups: list[GroupOut]
    progress: dict[str, int]
    warning: str = ""


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    material: Optional[str] = None
    brand: Optional[str] = None
    cost_cents: Optional[int] = None
    price_cents: Optional[int] = None
    count_override: Optional[int] = None
    include: Optional[bool] = None
    add_to_existing: Optional[bool] = None  # false = create a new item instead


class DetectionUpdate(BaseModel):
    include: bool


class BulkPrice(BaseModel):
    price_cents: Optional[int] = None
    cost_cents: Optional[int] = None
    category: Optional[str] = None  # only groups in this category; None = all


def _ref(item: Optional[Item]) -> Optional[ItemRef]:
    if not item:
        return None
    return ItemRef(id=item.id, sku=item.sku, name=item.name, size=item.size,
                   quantity=item.quantity, price_cents=item.price_cents)


def _get_batch(session: Session, batch_id: int) -> Batch:
    b = session.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "Batch not found")
    return b


def batch_out(session: Session, b: Batch, settings, warning: str = "") -> BatchOut:
    preset = PRESETS[b.preset]
    dets = session.exec(select(Detection).where(Detection.batch_id == b.id).order_by(Detection.number)).all()
    photos = []
    for p in session.exec(select(BatchPhoto).where(BatchPhoto.batch_id == b.id).order_by(BatchPhoto.id)).all():
        photos.append(PhotoOut(
            id=p.id, image_path=p.image_path, width=p.width, height=p.height,
            detections=[DetectionOut(id=d.id, number=d.number, bbox=json.loads(d.bbox),
                                     include=d.include, group_id=d.group_id)
                        for d in dets if d.photo_id == p.id],
        ))
    by_group: dict[int, list[Detection]] = {}
    for d in dets:
        by_group.setdefault(d.group_id, []).append(d)

    groups = []
    for g in session.exec(select(BatchGroup).where(BatchGroup.batch_id == b.id)).all():
        members = [d for d in by_group.get(g.id, []) if d.include]
        rep = next((d for d in members if d.id == g.rep_detection_id), members[0] if members else None)
        crops = ([rep.crop_path] if rep else []) + [d.crop_path for d in members if d is not rep][:3]
        groups.append(GroupOut(
            **g.model_dump(include={"id", "status", "name", "description", "category", "tags", "color",
                                    "size", "material", "brand", "cost_cents", "price_cents", "include",
                                    "count_override"}),
            count=bulk.group_count(session, g),
            numbers=[d.number for d in members],
            crops=crops,
            existing_item=_ref(session.get(Item, g.existing_item_id)) if g.existing_item_id else None,
            item=_ref(session.get(Item, g.item_id)) if g.item_id else None,
        ))
    groups.sort(key=lambda g: (g.numbers[0] if g.numbers else 10**9))

    live = [g for g in groups if g.include]
    progress = {
        "pieces": sum(1 for d in dets if d.include),
        "groups": len(live),
        "done": sum(1 for g in live if g.status == "done"),
        "failed": sum(1 for g in live if g.status == "failed"),
        "units": sum(g.count for g in live),
    }
    return BatchOut(
        id=b.id, preset=b.preset, preset_label=preset.label, mode=preset.mode,
        answers=json.loads(b.answers or "{}"), status=b.status, describing=bulk.is_running(settings, b.id),
        created_at=b.created_at, photos=photos, groups=groups, progress=progress, warning=warning,
    )


@router.get("/presets")
def list_presets():
    return [p.to_dict() for p in PRESETS.values()]


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(data: BatchCreate, request: Request, session: Session = Depends(get_session)):
    if data.preset not in PRESETS:
        raise HTTPException(400, f"Unknown product type '{data.preset}'")
    b = Batch(preset=data.preset, answers=json.dumps({k: v for k, v in data.answers.items() if v}))
    session.add(b)
    session.commit()
    session.refresh(b)
    return batch_out(session, b, shop_settings(request))


@router.get("/batches", response_model=list[BatchOut])
def list_batches(request: Request, open_only: bool = True, session: Session = Depends(get_session)):
    stmt = select(Batch).order_by(Batch.id.desc()).limit(20)
    if open_only:
        stmt = stmt.where(Batch.status != "saved")
    return [batch_out(session, b, shop_settings(request)) for b in session.exec(stmt).all()]


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: int, request: Request, session: Session = Depends(get_session)):
    return batch_out(session, _get_batch(session, batch_id), shop_settings(request))


@router.post("/batches/{batch_id}/photos", response_model=BatchOut)
async def add_photo(
    batch_id: int, request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    b = _get_batch(session, batch_id)
    if b.status == "saved":
        raise HTTPException(409, "This batch is already saved. Start a new one.")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is too large (max 25 MB)")
    try:
        img = load_image(data)
    except InvalidImage as exc:
        raise HTTPException(400, str(exc))
    warning = bulk.add_photo(session, request.app.state.ai, shop_settings(request), b, img)
    if b.status == "review":  # new photo after describing -> new pieces need describing
        b.status = "capturing"
        session.add(b)
        session.commit()
    return batch_out(session, b, shop_settings(request), warning)


@router.patch("/batches/{batch_id}/detections/{det_id}", response_model=BatchOut)
def update_detection(batch_id: int, det_id: int, body: DetectionUpdate, request: Request, session: Session = Depends(get_session)):
    b = _get_batch(session, batch_id)
    det = session.get(Detection, det_id)
    if not det or det.batch_id != batch_id:
        raise HTTPException(404, "Piece not found")
    bulk.set_detection_included(session, det, body.include)
    return batch_out(session, b, shop_settings(request))


class DescribeBody(BaseModel):
    # redo=True clears the AI's names/descriptions and runs again with `note`
    # (the seller's own words for what the items are).
    redo: bool = False
    note: str = Field(default="", max_length=300)


@router.post("/batches/{batch_id}/describe", response_model=BatchOut)
def describe(batch_id: int, request: Request, tasks: BackgroundTasks,
             body: Optional[DescribeBody] = None, session: Session = Depends(get_session)):
    b = _get_batch(session, batch_id)
    if b.status == "saved":
        raise HTTPException(409, "This batch is already saved.")
    shop = current_shop(request)
    if body and body.redo:
        if bulk.is_running(shop.settings, batch_id):
            raise HTTPException(409, "Still describing items - wait a moment.")
        bulk.reset_descriptions(session, b, body.note)
    b.status = "describing"
    session.add(b)
    session.commit()
    if bulk.start_describe(shop.settings, batch_id):
        tasks.add_task(bulk.describe_batch, shop.engine, request.app.state.ai, shop.settings, batch_id,
                       shop.info.ai_context, request.app.state.shops.style(shop.info))
    return batch_out(session, b, shop_settings(request))


@router.patch("/batches/{batch_id}/groups/{group_id}", response_model=BatchOut)
def update_group(batch_id: int, group_id: int, body: GroupUpdate, request: Request, session: Session = Depends(get_session)):
    b = _get_batch(session, batch_id)
    g = session.get(BatchGroup, group_id)
    if not g or g.batch_id != batch_id:
        raise HTTPException(404, "Item not found in this batch")
    changes = body.model_dump(exclude_unset=True)
    if changes.pop("add_to_existing", True) is False:
        g.existing_item_id = None
    if "count_override" in changes and changes["count_override"] is not None and changes["count_override"] < 0:
        raise HTTPException(400, "Count can't be negative")
    for k, v in changes.items():
        setattr(g, k, v)
    if g.name and g.status != "done":
        g.status = "done"  # the seller filled it in by hand
    session.add(g)
    session.commit()
    return batch_out(session, b, shop_settings(request))


@router.post("/batches/{batch_id}/bulk-edit", response_model=BatchOut)
def bulk_edit(batch_id: int, body: BulkPrice, request: Request, session: Session = Depends(get_session)):
    """e.g. 'all earrings $18' or 'every soap costs $2.10'."""
    b = _get_batch(session, batch_id)
    for g in session.exec(select(BatchGroup).where(BatchGroup.batch_id == batch_id)).all():
        if body.category and bulk.norm(g.category) != bulk.norm(body.category):
            continue
        if body.price_cents is not None:
            g.price_cents = body.price_cents
        if body.cost_cents is not None:
            g.cost_cents = body.cost_cents
        session.add(g)
    session.commit()
    return batch_out(session, b, shop_settings(request))


@router.post("/batches/{batch_id}/save", response_model=list[ItemRead])
def save(batch_id: int, request: Request, session: Session = Depends(get_session)):
    b = _get_batch(session, batch_id)
    if bulk.is_running(shop_settings(request), batch_id):
        raise HTTPException(409, "Still describing items - wait a moment.")
    prefix = current_shop(request).info.sku_prefix
    return bulk.save_batch(session, request.app.state.ai, b, lambda it: _auto_sku(it, prefix))


@router.delete("/batches/{batch_id}", status_code=204)
def discard(batch_id: int, request: Request, session: Session = Depends(get_session)):
    b = _get_batch(session, batch_id)
    if b.status == "saved":
        raise HTTPException(409, "Saved batches can't be discarded - their items are in inventory.")
    for model in (Detection, BatchGroup, BatchPhoto):
        for row in session.exec(select(model).where(model.batch_id == batch_id)).all():
            session.delete(row)
        session.flush()  # children first, so foreign keys stay valid
    session.delete(b)
    session.commit()
