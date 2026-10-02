from __future__ import annotations

import csv
import io
import re

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from ..db import get_session
from ..models import Item, ItemCreate, ItemRead, ItemUpdate, Sale, StockAdjust, StockMove, utcnow
from ..services import ledger
from ..services.images import load_image, resolve_image

router = APIRouter(prefix="/api/items", tags=["items"])


def _sku_prefix(item: Item) -> str:
    base = re.sub(r"[^A-Za-z]", "", item.category or item.name).upper()
    return (base[:3] or "ITM").ljust(3, "X")


def _auto_sku(item: Item) -> str:
    """TSH-00012, or TSH-00012-M / CAN-00003-8OZ when the item has a size."""
    size = re.sub(r"[^A-Za-z0-9]", "", item.size or "").upper()[:6]
    return f"{_sku_prefix(item)}-{item.id:05d}" + (f"-{size}" if size else "")


def _get(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _check_unique(session: Session, item: Item) -> None:
    if item.sku:
        clash = session.exec(select(Item).where(Item.sku == item.sku, Item.id != item.id)).first()
        if clash:
            raise HTTPException(409, f"SKU {item.sku} is already used by '{clash.name}'")
    if item.barcode:
        clash = session.exec(
            select(Item).where(Item.barcode == item.barcode, Item.id != item.id)
        ).first()
        if clash:
            raise HTTPException(409, f"Barcode {item.barcode} is already on '{clash.name}'")
    if item.size.strip():
        # Same product in the same size should be a restock, not a second item.
        same = session.exec(
            select(Item).where(
                func.lower(func.trim(Item.name)) == _norm(item.name),
                func.lower(func.trim(Item.size)) == _norm(item.size),
                Item.id != item.id,
            )
        ).first()
        if same:
            raise HTTPException(
                409,
                f"You already have '{same.name}' in size {same.size} ({same.quantity} in stock). "
                "Add stock to it instead.",
            )


def _index_image(request: Request, item: Item) -> None:
    if not item.image_path:
        item.embedding = item.embedding_model = None
        return
    try:
        path = resolve_image(request.app.state.settings.images_dir, item.image_path)
    except FileNotFoundError:
        raise HTTPException(400, "Image not found - scan the photo again")
    request.app.state.ai.index_item(item, load_image(path.read_bytes()))


SORTS = {
    "newest": (Item.created_at.desc(), Item.id.desc()),
    "oldest": (Item.created_at.asc(), Item.id.asc()),
    "name": (func.lower(Item.name).asc(), Item.size.asc()),
    "price_high": (Item.price_cents.desc(),),
    "price_low": (Item.price_cents.asc(),),
    "stock_low": (Item.quantity.asc(),),
    "stock_high": (Item.quantity.desc(),),
}


@router.get("", response_model=list[ItemRead])
def list_items(
    q: str = "",
    category: str = "",
    batch_id: Optional[int] = None,
    stock: Literal["all", "in", "low", "out"] = "all",
    material: str = "",
    sort: Literal["newest", "oldest", "name", "price_high", "price_low", "stock_low", "stock_high"] = "newest",
    low_stock: bool = False,  # kept for older clients; same as stock=low
    session: Session = Depends(get_session),
):
    stmt = select(Item)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Item.name.ilike(like),
                Item.sku.ilike(like),
                Item.tags.ilike(like),
                Item.category.ilike(like),
                Item.material.ilike(like),
                Item.barcode == q.strip(),
            )
        )
    if category:
        stmt = stmt.where(Item.category == category)
    if material:
        stmt = stmt.where(Item.material == material)
    if batch_id is not None:
        in_batch = select(StockMove.item_id).where(StockMove.batch_id == batch_id)
        stmt = stmt.where(Item.id.in_(in_batch))
    if low_stock:
        stock = "low"
    if stock == "in":
        stmt = stmt.where(Item.quantity > 0)
    elif stock == "low":
        stmt = stmt.where(Item.quantity > 0, Item.quantity <= Item.low_stock_threshold)
    elif stock == "out":
        stmt = stmt.where(Item.quantity <= 0)
    return session.exec(stmt.order_by(*SORTS[sort])).all()


class Facet(BaseModel):
    name: str
    items: int
    units: int


class BatchFacet(BaseModel):
    id: int
    label: str
    items: int


class Facets(BaseModel):
    total_items: int
    total_units: int
    stock_value_cents: int
    categories: list[Facet]
    materials: list[Facet]
    batches: list[BatchFacet]
    stock: dict[str, int]  # in / low / out


@router.get("/facets", response_model=Facets)
def facets(session: Session = Depends(get_session)):
    """Counts for the filter chips: categories, materials, batches, stock state."""
    from ..models import Batch
    from ..services.presets import PRESETS

    items = session.exec(select(Item)).all()

    def group(key) -> list[Facet]:
        acc: dict[str, list[int]] = {}
        for it in items:
            k = (key(it) or "").strip()
            if not k:
                continue
            a = acc.setdefault(k, [0, 0])
            a[0] += 1
            a[1] += max(it.quantity, 0)
        return sorted((Facet(name=k, items=v[0], units=v[1]) for k, v in acc.items()),
                      key=lambda f: (-f.items, f.name))

    batch_rows = session.exec(
        select(Batch, func.count(func.distinct(StockMove.item_id)))
        .join(StockMove, StockMove.batch_id == Batch.id)
        .group_by(Batch.id)
        .order_by(Batch.id.desc())
    ).all()
    batches = []
    for b, n in batch_rows:
        dt = b.created_at.astimezone()
        when = f"{dt:%b} {dt.day}"  # no %-d: it isn't supported on Windows
        label = f"#{b.id} · {PRESETS[b.preset].label if b.preset in PRESETS else b.preset} · {when}"
        batches.append(BatchFacet(id=b.id, label=label, items=n))

    return Facets(
        total_items=len(items),
        total_units=sum(max(i.quantity, 0) for i in items),
        stock_value_cents=sum(max(i.quantity, 0) * i.cost_cents for i in items),
        categories=group(lambda i: i.category),
        materials=group(lambda i: i.material),
        batches=batches,
        stock={
            "in": sum(1 for i in items if i.quantity > 0),
            "low": sum(1 for i in items if 0 < i.quantity <= i.low_stock_threshold),
            "out": sum(1 for i in items if i.quantity <= 0),
        },
    )


@router.get("/export.csv")
def export_items(session: Session = Depends(get_session)):
    items = session.exec(select(Item).order_by(Item.category, func.lower(Item.name))).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sku", "name", "category", "color", "size", "material", "barcode",
                "quantity", "cost", "price", "stock_value_at_cost", "tags", "description"])
    for i in items:
        w.writerow([i.sku, i.name, i.category, i.color, i.size, i.material, i.barcode or "",
                    i.quantity, f"{i.cost_cents/100:.2f}", f"{i.price_cents/100:.2f}",
                    f"{max(i.quantity, 0) * i.cost_cents/100:.2f}", i.tags, i.description])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


@router.get("/{item_id}/barcode.svg", include_in_schema=False)
def barcode_svg(item_id: int, session: Session = Depends(get_session)):
    """Code 128 barcode of the SKU, for printing price tags."""
    import zxingcpp
    from fastapi.responses import Response

    item = _get(session, item_id)
    code = zxingcpp.create_barcode(item.sku, zxingcpp.BarcodeFormat.Code128)
    return Response(zxingcpp.write_barcode_to_svg(code, scale=2), media_type="image/svg+xml",
                    headers={"Cache-Control": "max-age=3600"})


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, session: Session = Depends(get_session)):
    return _get(session, item_id)


@router.post("", response_model=ItemRead, status_code=201)
def create_item(data: ItemCreate, request: Request, session: Session = Depends(get_session)):
    item = Item.model_validate(data.model_dump(exclude={"sku", "quantity"}))
    item.quantity = 0  # opening stock goes through the ledger below
    item.sku = (data.sku or "").strip().upper()
    item.barcode = (item.barcode or "").strip() or None
    item.size = (item.size or "").strip()
    _check_unique(session, item)
    _index_image(request, item)
    session.add(item)
    session.flush()  # assigns id
    if not item.sku:
        item.sku = _auto_sku(item)
    ledger.move(session, item, data.quantity, "initial")
    session.commit()
    session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(
    item_id: int, data: ItemUpdate, request: Request, session: Session = Depends(get_session)
):
    item = _get(session, item_id)
    changes = data.model_dump(exclude_unset=True)
    new_qty = changes.pop("quantity", None)
    image_changed = "image_path" in changes and changes["image_path"] != item.image_path
    for key, val in changes.items():
        setattr(item, key, val)
    if "sku" in changes:
        item.sku = (item.sku or "").strip().upper() or _auto_sku(item)
    if "barcode" in changes:
        item.barcode = (item.barcode or "").strip() or None
    item.size = (item.size or "").strip()
    _check_unique(session, item)
    if image_changed:
        _index_image(request, item)
    if new_qty is not None:
        ledger.move(session, item, new_qty - item.quantity, "adjust", note="count edited")
    item.updated_at = utcnow()
    session.commit()
    session.refresh(item)
    return item


@router.post("/{item_id}/adjust", response_model=ItemRead)
def adjust_stock(item_id: int, data: StockAdjust, session: Session = Depends(get_session)):
    item = _get(session, item_id)
    ledger.move(session, item, data.delta, "adjust")
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, session: Session = Depends(get_session)):
    item = _get(session, item_id)
    sales = session.exec(select(func.count()).select_from(Sale).where(Sale.item_id == item_id)).one()
    if sales:
        raise HTTPException(
            409, "This item has sales history, so it can't be deleted. Set its stock to 0 instead."
        )
    for mv in session.exec(select(StockMove).where(StockMove.item_id == item_id)).all():
        session.delete(mv)
    session.delete(item)
    session.commit()
