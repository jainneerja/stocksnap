"""Plain-language money reports: what came in, what the goods cost, what you
spent, what's left. Deliberately no tax calculation - export the CSV for your
accountant or tax software."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Expense, Item, Sale, StockMove
from .sales import day_range

router = APIRouter(prefix="/api/reports", tags=["reports"])


class TopItem(BaseModel):
    item_id: int
    name: str
    units: int
    revenue_cents: int
    profit_cents: int


class Summary(BaseModel):
    start: date
    end: date
    sales_count: int
    units_sold: int
    revenue_cents: int
    cogs_cents: int  # cost of goods sold
    gross_profit_cents: int
    expenses_cents: int
    net_profit_cents: int
    stock_value_cents: int  # current inventory at cost
    expenses_by_category: dict[str, int]
    top_items: list[TopItem]


def _rows(session: Session, start: Optional[date], end: Optional[date]):
    lo, hi = day_range(start, end)
    sales = session.exec(select(Sale).where(Sale.sold_at >= lo, Sale.sold_at < hi)).all()
    expenses = session.exec(
        select(Expense).where(Expense.spent_on >= lo.date(), Expense.spent_on < hi.date())
    ).all()
    return lo.date(), (hi.date().toordinal() - 1), sales, expenses


@router.get("/summary", response_model=Summary)
def summary(
    start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(get_session)
):
    lo, hi_ord, sales, expenses = _rows(session, start, end)
    revenue = sum(s.quantity * s.unit_price_cents for s in sales)
    cogs = sum(s.quantity * s.unit_cost_cents for s in sales)
    spent = sum(e.amount_cents for e in expenses)

    by_cat: dict[str, int] = defaultdict(int)
    for e in expenses:
        by_cat[e.category or "General"] += e.amount_cents

    per_item: dict[int, TopItem] = {}
    for s in sales:
        t = per_item.setdefault(
            s.item_id, TopItem(item_id=s.item_id, name=s.item_name, units=0, revenue_cents=0, profit_cents=0)
        )
        t.units += s.quantity
        t.revenue_cents += s.quantity * s.unit_price_cents
        t.profit_cents += s.quantity * (s.unit_price_cents - s.unit_cost_cents)

    stock_value = sum(
        max(q, 0) * c for q, c in session.exec(select(Item.quantity, Item.cost_cents)).all()
    )
    return Summary(
        start=lo,
        end=date.fromordinal(hi_ord),
        sales_count=len(sales),
        units_sold=sum(s.quantity for s in sales),
        revenue_cents=revenue,
        cogs_cents=cogs,
        gross_profit_cents=revenue - cogs,
        expenses_cents=spent,
        net_profit_cents=revenue - cogs - spent,
        stock_value_cents=stock_value,
        expenses_by_category=dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        top_items=sorted(per_item.values(), key=lambda t: -t.revenue_cents)[:5],
    )


def _money(cents: int) -> str:
    return f"{cents / 100:.2f}"


@router.get("/export.csv")
def export_csv(
    kind: Literal["sales", "expenses", "summary"] = "sales",
    start: Optional[date] = None,
    end: Optional[date] = None,
    session: Session = Depends(get_session),
):
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "summary":
        s = summary(start, end, session)
        w.writerow(["metric", "amount"])
        w.writerow(["period", f"{s.start} to {s.end}"])
        for label, val in [
            ("revenue", s.revenue_cents),
            ("cost_of_goods_sold", s.cogs_cents),
            ("gross_profit", s.gross_profit_cents),
            ("expenses", s.expenses_cents),
            ("net_profit", s.net_profit_cents),
        ]:
            w.writerow([label, _money(val)])
        w.writerow(["units_sold", s.units_sold])
        for cat, amt in s.expenses_by_category.items():
            w.writerow([f"expense:{cat}", _money(amt)])
    else:
        _, _, sales, expenses = _rows(session, start, end)
        if kind == "sales":
            w.writerow(["date", "item", "quantity", "unit_price", "unit_cost", "revenue", "profit", "note"])
            for s in sorted(sales, key=lambda x: x.sold_at):
                w.writerow([
                    s.sold_at.astimezone().date().isoformat(), s.item_name, s.quantity,
                    _money(s.unit_price_cents), _money(s.unit_cost_cents),
                    _money(s.quantity * s.unit_price_cents),
                    _money(s.quantity * (s.unit_price_cents - s.unit_cost_cents)), s.note,
                ])
        else:
            w.writerow(["date", "category", "description", "amount"])
            for e in sorted(expenses, key=lambda x: x.spent_on):
                w.writerow([e.spent_on.isoformat(), e.category, e.description, _money(e.amount_cents)])

    fname = f"stocksnap-{kind}-{start or 'month'}-{end or 'today'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ------------------------------------------------------------ monthly stock


class StockRow(BaseModel):
    item_id: int
    sku: str
    name: str
    size: str
    category: str
    image_path: Optional[str]
    opening: int
    added: int  # new stock: initial + bulk/scan intake
    sold: int  # net of undone sales
    adjusted: int  # manual corrections (+ or -)
    closing: int
    unit_cost_cents: int
    closing_value_cents: int


class CategoryStock(BaseModel):
    category: str
    items: int
    opening: int
    added: int
    sold: int
    adjusted: int
    closing: int
    closing_value_cents: int


class StockMonth(BaseModel):
    month: str  # YYYY-MM
    rows: list[StockRow]  # sorted by category, then name
    by_category: list[CategoryStock]  # biggest first
    totals: dict[str, int]


def _month_bounds(month: Optional[str]) -> tuple[str, datetime, datetime]:
    from .sales import local_today

    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            first = date(y, m, 1)
        except ValueError:
            raise HTTPException(400, "month must look like 2026-10")
    else:
        first = local_today().replace(day=1)
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    lo = datetime.combine(first, time.min).astimezone()
    hi = datetime.combine(nxt, time.min).astimezone()
    return first.strftime("%Y-%m"), lo, hi


@router.get("/stock", response_model=StockMonth)
def stock_by_month(
    month: Optional[str] = None, category: str = "", session: Session = Depends(get_session)
):
    """Opening, added, sold, adjusted and closing stock for every item in a month."""
    label, lo, hi = _month_bounds(month)
    moves = session.exec(select(StockMove).where(StockMove.created_at < hi)).all()
    items = {i.id: i for i in session.exec(select(Item)).all()}

    acc: dict[int, dict[str, int]] = defaultdict(lambda: dict(opening=0, added=0, sold=0, adjusted=0))
    for mv in moves:
        a = acc[mv.item_id]
        if mv.created_at < lo:
            a["opening"] += mv.delta
        elif mv.reason in ("initial", "intake"):
            a["added"] += mv.delta
        elif mv.reason in ("sale", "void"):
            a["sold"] -= mv.delta
        else:
            a["adjusted"] += mv.delta

    rows = []
    for item_id, a in acc.items():
        it = items.get(item_id)
        if it is None:
            continue
        closing = a["opening"] + a["added"] - a["sold"] + a["adjusted"]
        if not any(a.values()) and not closing:
            continue
        if category and it.category != category:
            continue
        rows.append(StockRow(
            item_id=item_id, sku=it.sku, name=it.name, size=it.size, closing=closing,
            category=it.category or "Uncategorised", image_path=it.image_path,
            unit_cost_cents=it.cost_cents, closing_value_cents=max(closing, 0) * it.cost_cents, **a,
        ))
    rows.sort(key=lambda r: (r.category.lower(), r.name.lower(), r.size))
    keys = ("opening", "added", "sold", "adjusted", "closing", "closing_value_cents")
    cats: dict[str, CategoryStock] = {}
    for r in rows:
        c = cats.setdefault(r.category, CategoryStock(category=r.category, items=0, **{k: 0 for k in keys}))
        c.items += 1
        for k in keys:
            setattr(c, k, getattr(c, k) + getattr(r, k))
    by_category = sorted(cats.values(), key=lambda c: (-c.closing, -c.items, c.category))
    totals = {k: sum(getattr(r, k) for r in rows) for k in keys}
    return StockMonth(month=label, rows=rows, by_category=by_category, totals=totals)


@router.get("/stock.csv")
def stock_csv(month: Optional[str] = None, category: str = "", session: Session = Depends(get_session)):
    rep = stock_by_month(month, category, session)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["category", "sku", "item", "size", "opening", "added", "sold", "adjusted", "closing",
                "unit_cost", "closing_value"])
    for r in rep.rows:
        w.writerow([r.category, r.sku, r.name, r.size, r.opening, r.added, r.sold, r.adjusted, r.closing,
                    _money(r.unit_cost_cents), _money(r.closing_value_cents)])
    w.writerow([])
    for c in rep.by_category:
        w.writerow([c.category, "", f"SUBTOTAL ({c.items} items)", "", c.opening, c.added, c.sold,
                    c.adjusted, c.closing, "", _money(c.closing_value_cents)])
    t = rep.totals
    w.writerow(["ALL", "", "TOTAL", "", t["opening"], t["added"], t["sold"], t["adjusted"], t["closing"],
                "", _money(t["closing_value_cents"])])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=stocksnap-stock-{rep.month}.csv"},
    )
