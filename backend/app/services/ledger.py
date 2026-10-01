"""Single place that changes stock, so the ledger can never drift from
Item.quantity."""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from ..models import Item, StockMove, utcnow


def move(
    session: Session,
    item: Item,
    delta: int,
    reason: str,
    *,
    sale_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    note: str = "",
) -> None:
    if delta == 0:
        return
    if item.id is None:
        session.flush()
    item.quantity += delta
    item.updated_at = utcnow()
    session.add(
        StockMove(
            item_id=item.id,
            delta=delta,
            reason=reason,
            unit_cost_cents=item.cost_cents,
            sale_id=sale_id,
            batch_id=batch_id,
            note=note,
        )
    )
