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
