from datetime import date

import pytest

from app.services.vision import parse_draft
from conftest import barcode_photo, photo


def new_item(client, **overrides):
    body = {"name": "Candle", "category": "Candle", "cost_cents": 400,
            "price_cents": 1500, "quantity": 5}
    body.update(overrides)
    r = client.post("/api/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, data, name="p.jpg"):
    r = client.post("/api/scan", files={"file": (name, data, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- inventory


def test_create_item_generates_sku(client):
    item = new_item(client, category="T-shirt")
    assert item["sku"] == f"TSH-{item['id']:05d}"


def test_duplicate_sku_and_barcode_rejected(client):
    new_item(client, sku="abc-1", barcode="123")
    assert client.post("/api/items", json={"name": "x", "sku": "ABC-1"}).status_code == 409
    assert client.post("/api/items", json={"name": "y", "barcode": "123"}).status_code == 409


def test_search_update_adjust_and_low_stock(client):
    a = new_item(client, name="Lavender candle", tags="lavender,soy", quantity=10)
    new_item(client, name="Mug", category="Mug", quantity=1)
    assert [i["name"] for i in client.get("/api/items?q=lavender").json()] == ["Lavender candle"]
    assert [i["name"] for i in client.get("/api/items?low_stock=true").json()] == ["Mug"]

    r = client.patch(f"/api/items/{a['id']}", json={"price_cents": 1800})
    assert r.json()["price_cents"] == 1800
    r = client.post(f"/api/items/{a['id']}/adjust", json={"delta": -3})
    assert r.json()["quantity"] == 7


def test_inventory_csv(client):
    new_item(client, name="Mug", quantity=3, cost_cents=250)
    text = client.get("/api/items/export.csv").text
    assert "Mug" in text and "7.50" in text  # 3 x $2.50 stock value


# -------------------------------------------------------------------- sales


def test_sale_reduces_stock_and_void_restores(client):
    item = new_item(client, quantity=5)
    sale = client.post("/api/sales", json={"item_id": item["id"], "quantity": 2}).json()
    assert sale["unit_price_cents"] == 1500 and sale["unit_cost_cents"] == 400
    assert client.get(f"/api/items/{item['id']}").json()["quantity"] == 3

    assert client.delete(f"/api/sales/{sale['id']}").status_code == 204
    assert client.get(f"/api/items/{item['id']}").json()["quantity"] == 5


def test_cannot_oversell(client):
    item = new_item(client, quantity=1)
    r = client.post("/api/sales", json={"item_id": item["id"], "quantity": 2})
    assert r.status_code == 409
    assert client.get(f"/api/items/{item['id']}").json()["quantity"] == 1


def test_item_with_sales_cannot_be_deleted(client):
    item = new_item(client)
    client.post("/api/sales", json={"item_id": item["id"]})
    assert client.delete(f"/api/items/{item['id']}").status_code == 409


# ------------------------------------------------------------------ reports


def test_monthly_summary(client):
    item = new_item(client, quantity=10, cost_cents=400, price_cents=1500)
    client.post("/api/sales", json={"item_id": item["id"], "quantity": 3})
    client.post("/api/sales", json={"item_id": item["id"], "quantity": 1, "unit_price_cents": 1000})
    client.post("/api/expenses", json={"category": "Booth fee", "amount_cents": 2500})

    today = date.today().isoformat()
    s = client.get(f"/api/reports/summary?start={today}&end={today}").json()
    assert s["units_sold"] == 4
    assert s["revenue_cents"] == 3 * 1500 + 1000
    assert s["cogs_cents"] == 4 * 400
    assert s["gross_profit_cents"] == 5500 - 1600
    assert s["expenses_cents"] == 2500
    assert s["net_profit_cents"] == 5500 - 1600 - 2500
    assert s["stock_value_cents"] == 6 * 400
    assert s["expenses_by_category"] == {"Booth fee": 2500}
    assert s["top_items"][0]["units"] == 4

    for kind in ("sales", "expenses", "summary"):
        r = client.get(f"/api/reports/export.csv?kind={kind}&start={today}&end={today}")
        assert r.status_code == 200 and r.text.count("\n") >= 2


def test_bad_date_range(client):
    assert client.get("/api/reports/summary?start=2026-02-01&end=2026-01-01").status_code == 400


# --------------------------------------------------------------- scan + AI


def test_scan_reads_barcode_and_finds_item(client):
    pytest.importorskip("zxingcpp")
    new_item(client, name="Store-bought wick", barcode="4006381333931")
    res = upload(client, barcode_photo("4006381333931"), "b.png")
    assert res["barcode"] == "4006381333931"
    assert res["barcode_item"]["name"] == "Store-bought wick"


def test_scan_matches_visually_similar_item(client):
    pink = upload(client, photo((220, 60, 120), "circle"))
    item = new_item(client, name="Pink tee", image_path=pink["image_path"])

    again = upload(client, photo((222, 62, 118), "circle"))
    assert again["matches"] and again["matches"][0]["item"]["id"] == item["id"]

    other = upload(client, photo((30, 90, 200), "rect"))
    assert all(m["item"]["id"] != item["id"] for m in other["matches"])


def test_describe_returns_ai_draft(client):
    res = upload(client, photo())
    draft = client.post("/api/describe", json={"image_path": res["image_path"]}).json()
    assert draft["category"] == "T-shirt" and "floral" in draft["tags"]


def test_describe_fails_gracefully(make_client):
    c = make_client(vision_fails=True)
    res = upload(c, photo())
    r = c.post("/api/describe", json={"image_path": res["image_path"]})
    assert r.status_code == 503 and "fill in" in r.json()["detail"]


def test_describe_blocks_path_traversal(client):
    assert client.post("/api/describe", json={"image_path": "../stocksnap.db"}).status_code == 404


def test_bad_upload(client):
    r = client.post("/api/scan", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_parse_draft_tolerates_messy_model_output():
    d = parse_draft('Sure! {"name": "Blue Mug", "tags": "Coffee, Ceramic", "color": ["blue","white"]}')
    assert d.name == "Blue Mug" and d.tags == ["coffee", "ceramic"] and d.color == "blue, white"
    assert parse_draft("no json here").name == ""


# ------------------------------------------------------------------- system


def test_health_and_backup(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["matcher"]["model"] == "lite-v1"
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.content[:2] == b"PK"
