from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Expense, ExpenseCreate, Item, Sale, SaleCreate, local_today, utcnow
from ..services import ledger

router = APIRouter(prefix="/api", tags=["sales & expenses"])


def day_range(start: Optional[date], end: Optional[date]) -> tuple[datetime, datetime]:
    """Whole local days [start, end] -> aware datetimes. Defaults to this month so far."""
    end = end or local_today()
    start = start or end.replace(day=1)
    if start > end:
        raise HTTPException(400, "start must be on or before end")
    lo = datetime.combine(start, time.min).astimezone()
    hi = datetime.combine(end + timedelta(days=1), time.min).astimezone()
    return lo, hi


# ------------------------------------------------------------------ sales


@router.post("/sales", response_model=Sale, status_code=201)
def create_sale(data: SaleCreate, session: Session = Depends(get_session)):
    item = session.get(Item, data.item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.quantity < data.quantity:
        raise HTTPException(
            409, f"Only {item.quantity} of '{item.name}' in stock. Restock first or adjust the count."
        )
    sale = Sale(
        item_id=item.id,
        item_name=item.name,
        quantity=data.quantity,
        unit_price_cents=item.price_cents if data.unit_price_cents is None else data.unit_price_cents,
        unit_cost_cents=item.cost_cents,
        note=data.note,
        sold_at=data.sold_at or utcnow(),
    )
    session.add(sale)
    session.flush()
    ledger.move(session, item, -data.quantity, "sale", sale_id=sale.id)
    session.commit()  # sale + stock change in one transaction
    session.refresh(sale)
    return sale


@router.get("/sales", response_model=list[Sale])
def list_sales(
    start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(get_session)
):
    lo, hi = day_range(start, end)
    stmt = select(Sale).where(Sale.sold_at >= lo, Sale.sold_at < hi).order_by(Sale.sold_at.desc())
    return session.exec(stmt).all()


@router.delete("/sales/{sale_id}", status_code=204)
def void_sale(sale_id: int, session: Session = Depends(get_session)):
    """Undo a sale (e.g. mistake or refund) and put the stock back."""
    sale = session.get(Sale, sale_id)
    if not sale:
        raise HTTPException(404, "Sale not found")
    item = session.get(Item, sale.item_id)
    if item:
        ledger.move(session, item, sale.quantity, "void", sale_id=sale.id, note="sale undone")
    session.delete(sale)
    session.commit()


# --------------------------------------------------------------- expenses


@router.post("/expenses", response_model=Expense, status_code=201)
def create_expense(data: ExpenseCreate, session: Session = Depends(get_session)):
    exp = Expense.model_validate(data)
    session.add(exp)
    session.commit()
    session.refresh(exp)
    return exp


@router.get("/expenses", response_model=list[Expense])
def list_expenses(
    start: Optional[date] = None, end: Optional[date] = None, session: Session = Depends(get_session)
):
    lo, hi = day_range(start, end)
    stmt = (
        select(Expense)
        .where(Expense.spent_on >= lo.date(), Expense.spent_on < hi.date())
        .order_by(Expense.spent_on.desc())
    )
    return session.exec(stmt).all()


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, session: Session = Depends(get_session)):
    exp = session.get(Expense, expense_id)
    if not exp:
        raise HTTPException(404, "Expense not found")
    session.delete(exp)
    session.commit()
