"""Database tables and API schemas.

Money is stored as integer cents to avoid floating-point rounding errors.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timestamps are stored timezone-aware in UTC and shown in local time."""
    return datetime.now(timezone.utc)


def local_today() -> date:
    return datetime.now().astimezone().date()


# ---------------------------------------------------------------- items


class ItemBase(SQLModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = ""
    tags: str = ""  # comma-separated
    color: str = ""
    size: str = ""
    material: str = ""
    barcode: Optional[str] = Field(default=None, index=True)
    cost_cents: int = Field(default=0, ge=0)
    price_cents: int = Field(default=0, ge=0)
    quantity: int = 0
    low_stock_threshold: int = Field(default=2, ge=0)
    image_path: Optional[str] = None
    attributes: str = ""  # JSON object of extra facts, e.g. {"Metal": "Sterling silver"}


class Item(ItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sku: str = Field(default="", index=True)
    embedding: Optional[str] = None  # JSON list[float]
    embedding_model: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ItemCreate(ItemBase):
    sku: Optional[str] = None


class ItemUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    material: Optional[str] = None
    barcode: Optional[str] = None
    sku: Optional[str] = None
    cost_cents: Optional[int] = Field(default=None, ge=0)
    price_cents: Optional[int] = Field(default=None, ge=0)
    quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    image_path: Optional[str] = None
    attributes: Optional[str] = None


class ItemRead(ItemBase):
    id: int
    sku: str
    created_at: datetime
    updated_at: datetime


class StockAdjust(SQLModel):
    delta: int  # +5 = restocked five, -1 = one broken


# ---------------------------------------------------------------- sales


class Sale(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    item_name: str = ""  # snapshot so reports survive item renames/deletes
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    unit_cost_cents: int = Field(ge=0)  # snapshot for accurate COGS
    note: str = ""
    sold_at: datetime = Field(default_factory=utcnow, index=True)


class SaleCreate(SQLModel):
    item_id: int
    quantity: int = Field(default=1, gt=0)
    unit_price_cents: Optional[int] = Field(default=None, ge=0)  # defaults to item price
    note: str = ""
    sold_at: Optional[datetime] = None


# ---------------------------------------------------------------- expenses


class ExpenseBase(SQLModel):
    category: str = "General"
    description: str = ""
    amount_cents: int = Field(gt=0)
    spent_on: date = Field(default_factory=local_today, index=True)


class Expense(ExpenseBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class ExpenseCreate(ExpenseBase):
    pass


# ------------------------------------------------------------ stock ledger


class StockMove(SQLModel, table=True):
    """Every change to stock, so any month can be reconstructed.

    reason: initial | intake | sale | void | adjust
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    delta: int
    reason: str = Field(index=True)
    unit_cost_cents: int = 0
    sale_id: Optional[int] = None
    batch_id: Optional[int] = None
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)


# ------------------------------------------------------------ bulk intake


class Batch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    preset: str
    answers: str = "{}"  # JSON: batch-question answers applied to every piece
    status: str = "capturing"  # capturing | describing | review | saved
    created_at: datetime = Field(default_factory=utcnow)


class BatchPhoto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="batch.id", index=True)
    image_path: str
    width: int
    height: int
    created_at: datetime = Field(default_factory=utcnow)


class Detection(SQLModel, table=True):
    """One piece found on a tray photo."""

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="batch.id", index=True)
    photo_id: int = Field(foreign_key="batchphoto.id", index=True)
    number: int  # 1-based, matches the number drawn on the photo
    bbox: str  # JSON [x, y, w, h] in photo pixels
    crop_path: str
    include: bool = True
    group_id: int = 0  # identical goods share a group; unique mode = own group
    embedding: Optional[str] = None


class BatchGroup(SQLModel, table=True):
    """What becomes one inventory item. In one-of-a-kind mode each piece is its
    own group; in identical-goods mode look-alike pieces share a group."""

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="batch.id", index=True)
    rep_detection_id: int  # the piece the AI looks at
    status: str = "pending"  # pending | done | failed
    name: str = ""
    description: str = ""
    category: str = ""
    tags: str = ""
    color: str = ""
    size: str = ""
    material: str = ""
    cost_cents: int = 0
    price_cents: int = 0
    count_override: Optional[int] = None  # e.g. stacked soaps the camera can't count
    include: bool = True
    existing_item_id: Optional[int] = None  # same product already in inventory
    item_id: Optional[int] = None  # set once saved
