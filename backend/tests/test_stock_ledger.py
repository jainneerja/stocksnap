import sqlite3
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config import Settings
from app.db import make_engine
from app.models import Item, StockMove


def _item(client, **kw):
    body = {"name": "Lavender soap", "category": "Soap", "cost_cents": 200, "price_cents": 600, "quantity": 10}
    body.update(kw)
    return client.post("/api/items", json=body).json()


def test_every_change_is_in_the_ledger(client):
    it = _item(client)
    sale = client.post("/api/sales", json={"item_id": it["id"], "quantity": 3}).json()
    client.post("/api/sales", json={"item_id": it["id"], "quantity": 1})
    client.delete(f"/api/sales/{sale['id']}")                       # undo 3
    client.post(f"/api/items/{it['id']}/adjust", json={"delta": -1})  # one broken
    client.patch(f"/api/items/{it['id']}", json={"quantity": 12})     # recount: 8 -> 12

    rep = client.get("/api/reports/stock").json()
    row = rep["rows"][0]
    assert row == {**row, "opening": 0, "added": 10, "sold": 1, "adjusted": 3, "closing": 12}
    assert row["closing"] == client.get(f"/api/items/{it['id']}").json()["quantity"]
    assert row["closing_value_cents"] == 12 * 200
    assert rep["totals"]["closing"] == 12
    csv = client.get(f"/api/reports/stock.csv?month={rep['month']}").text
    assert "Lavender soap" in csv and "TOTAL" in csv and "Soap" in csv


def test_opening_comes_from_earlier_months(client):
    it = _item(client, quantity=5)
    # move the opening stock into last month
    reg = client.app.state.shops
    engine = reg.context(reg.list()[0]).engine
    with Session(engine) as s:
        mv = s.exec(select(StockMove).where(StockMove.item_id == it["id"])).one()
        mv.created_at = datetime.now(timezone.utc) - timedelta(days=40)
        s.add(mv)
        s.commit()
    client.post("/api/sales", json={"item_id": it["id"], "quantity": 2})
    row = client.get("/api/reports/stock").json()["rows"][0]
    assert (row["opening"], row["added"], row["sold"], row["closing"]) == (5, 0, 2, 3)


def test_bad_month(client):
    assert client.get("/api/reports/stock?month=oct").status_code == 400


def test_migration_from_v01_database(tmp_path):
    data = tmp_path / "old"
    data.mkdir()
    db = sqlite3.connect(data / "stocksnap.db")
    db.executescript("""
      CREATE TABLE item (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, description VARCHAR NOT NULL,
        category VARCHAR NOT NULL, tags VARCHAR NOT NULL, color VARCHAR NOT NULL, size VARCHAR NOT NULL,
        material VARCHAR NOT NULL, barcode VARCHAR, cost_cents INTEGER NOT NULL, price_cents INTEGER NOT NULL,
        quantity INTEGER NOT NULL, low_stock_threshold INTEGER NOT NULL, image_path VARCHAR,
        sku VARCHAR NOT NULL, embedding VARCHAR, embedding_model VARCHAR,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
      CREATE TABLE sale (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, item_name VARCHAR NOT NULL,
        quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL, unit_cost_cents INTEGER NOT NULL,
        note VARCHAR NOT NULL, sold_at DATETIME NOT NULL);
      INSERT INTO item VALUES (1,'Mug','','','','','','',NULL,300,1200,4,2,NULL,'MUG-00001',NULL,NULL,
        '2026-08-01 10:00:00.000000','2026-08-01 10:00:00.000000');
      INSERT INTO sale VALUES (1,1,'Mug',2,1200,300,'','2026-08-10 10:00:00.000000');
    """)
    db.commit()
    db.close()

    engine = make_engine(Settings(data_dir=data))
    with Session(engine) as s:
        item = s.get(Item, 1)
        assert item.attributes == ""
        moves = s.exec(select(StockMove)).all()
        assert sorted((m.reason, m.delta) for m in moves) == [("initial", 6), ("sale", -2)]
    make_engine(Settings(data_dir=data))  # running again changes nothing
    with Session(engine) as s:
        assert len(s.exec(select(StockMove)).all()) == 2


def test_stock_grouped_by_category(client):
    _item(client, name="Hoops", category="Earrings", quantity=4)
    _item(client, name="Studs", category="Earrings", quantity=6)
    r = _item(client, name="Band", category="Rings", quantity=3)
    client.post("/api/sales", json={"item_id": r["id"], "quantity": 1})

    rep = client.get("/api/reports/stock").json()
    cats = {c["category"]: c for c in rep["by_category"]}
    assert cats["Earrings"]["items"] == 2 and cats["Earrings"]["closing"] == 10
    assert cats["Rings"]["sold"] == 1 and cats["Rings"]["closing"] == 2
    assert rep["by_category"][0]["category"] == "Earrings"          # biggest first
    assert [x["name"] for x in rep["rows"]] == ["Hoops", "Studs", "Band"]
    only = client.get("/api/reports/stock", params={"category": "Rings"}).json()
    assert [x["name"] for x in only["rows"]] == ["Band"] and only["totals"]["closing"] == 2
    assert "SUBTOTAL" in client.get("/api/reports/stock.csv").text
