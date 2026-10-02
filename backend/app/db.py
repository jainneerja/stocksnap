from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import Settings


def make_engine(settings: Settings):
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    return engine


# Columns added after v0.1. SQLite's create_all never alters existing tables,
# so add them here (idempotent, safe to run on every start).
_NEW_COLUMNS = {
    "item": {"attributes": "VARCHAR NOT NULL DEFAULT ''"},
}


def _migrate(engine) -> None:
    from sqlmodel import Session, select

    from .models import Item, Sale, StockMove

    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            have = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    _tidy_bulk_categories(engine)

    # Backfill the stock ledger for data created before it existed.
    with Session(engine) as s:
        if s.exec(select(StockMove.id).limit(1)).first() is not None:
            return
        items = s.exec(select(Item)).all()
        if not items:
            return
        sales = s.exec(select(Sale)).all()
        sold: dict[int, int] = {}
        for sale in sales:
            sold[sale.item_id] = sold.get(sale.item_id, 0) + sale.quantity
            s.add(StockMove(item_id=sale.item_id, delta=-sale.quantity, reason="sale",
                            unit_cost_cents=sale.unit_cost_cents, sale_id=sale.id,
                            created_at=sale.sold_at))
        for it in items:
            opening = it.quantity + sold.get(it.id, 0)
            if opening:
                s.add(StockMove(item_id=it.id, delta=opening, reason="initial",
                                unit_cost_cents=it.cost_cents, created_at=it.created_at))
        s.commit()


def _tidy_bulk_categories(engine) -> None:
    """Items added by bulk intake before categories were fixed lists get mapped
    onto their product type's list (e.g. "Brooch" -> "Pins & Brooches")."""
    from sqlmodel import Session, select

    from .models import Batch, Item, StockMove
    from .services.presets import PRESETS, normalize_category

    with Session(engine) as s:
        rows = s.exec(
            select(Item, Batch.preset)
            .join(StockMove, StockMove.item_id == Item.id)
            .join(Batch, Batch.id == StockMove.batch_id)
        ).all()
        changed = False
        for item, preset_key in rows:
            preset = PRESETS.get(preset_key)
            if not preset or not preset.categories or item.category in preset.categories:
                continue
            cat = normalize_category(item.category, preset.categories)
            if cat == preset.categories[-1]:  # category unhelpful ("Jewellery") - try the name
                cat = normalize_category(item.name, preset.categories)
            item.category = cat
            s.add(item)
            changed = True
        if changed:
            s.commit()


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
