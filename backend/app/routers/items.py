from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlmodel import Session, select

from ..db import get_session
from ..models import Item, ItemCreate, ItemRead, ItemUpdate, Sale, StockAdjust, utcnow
from ..services.images import load_image, resolve_image

router = APIRouter(prefix="/api/items", tags=["items"])


def _sku_prefix(item: Item) -> str:
    base = re.sub(r"[^A-Za-z]", "", item.category or item.name).upper()
    return (base[:3] or "ITM").ljust(3, "X")


def _get(session: Session, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


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


def _index_image(request: Request, item: Item) -> None:
    if not item.image_path:
        item.embedding = item.embedding_model = None
        return
    try:
        path = resolve_image(request.app.state.settings.images_dir, item.image_path)
    except FileNotFoundError:
        raise HTTPException(400, "Image not found - scan the photo again")
    request.app.state.ai.index_item(item, load_image(path.read_bytes()))


@router.get("", response_model=list[ItemRead])
def list_items(
    q: str = "", low_stock: bool = False, session: Session = Depends(get_session)
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
                Item.barcode == q.strip(),
            )
        )
    if low_stock:
        stmt = stmt.where(Item.quantity <= Item.low_stock_threshold)
    return session.exec(stmt.order_by(Item.updated_at.desc())).all()


@router.get("/export.csv")
def export_items(session: Session = Depends(get_session)):
    items = session.exec(select(Item).order_by(Item.sku)).all()
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


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, session: Session = Depends(get_session)):
    return _get(session, item_id)


@router.post("", response_model=ItemRead, status_code=201)
def create_item(data: ItemCreate, request: Request, session: Session = Depends(get_session)):
    item = Item.model_validate(data.model_dump(exclude={"sku"}))
    item.sku = (data.sku or "").strip().upper()
    item.barcode = (item.barcode or "").strip() or None
    _check_unique(session, item)
    _index_image(request, item)
    session.add(item)
    session.flush()  # assigns id
    if not item.sku:
        item.sku = f"{_sku_prefix(item)}-{item.id:05d}"
    session.commit()
    session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(
    item_id: int, data: ItemUpdate, request: Request, session: Session = Depends(get_session)
):
    item = _get(session, item_id)
    changes = data.model_dump(exclude_unset=True)
    image_changed = "image_path" in changes and changes["image_path"] != item.image_path
    for key, val in changes.items():
        setattr(item, key, val)
    if "sku" in changes:
        item.sku = (item.sku or "").strip().upper() or f"{_sku_prefix(item)}-{item.id:05d}"
    if "barcode" in changes:
        item.barcode = (item.barcode or "").strip() or None
    _check_unique(session, item)
    if image_changed:
        _index_image(request, item)
    item.updated_at = utcnow()
    session.commit()
    session.refresh(item)
    return item


@router.post("/{item_id}/adjust", response_model=ItemRead)
def adjust_stock(item_id: int, data: StockAdjust, session: Session = Depends(get_session)):
    item = _get(session, item_id)
    item.quantity += data.delta
    item.updated_at = utcnow()
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
    session.delete(item)
    session.commit()
