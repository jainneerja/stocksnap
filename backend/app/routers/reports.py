"""Plain-language money reports: what came in, what the goods cost, what you
spent, what's left. Deliberately no tax calculation - export the CSV for your
accountant or tax software."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Expense, Item, Sale
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
