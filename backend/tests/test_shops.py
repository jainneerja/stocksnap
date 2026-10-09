import io

from PIL import Image

from conftest import photo


def test_no_shop_yet_asks_for_setup(make_client):
    c = make_client(with_shop=False)
    r = c.get("/api/shops").json()
    assert r["shops"] == [] and r["current"] is None and "clothing" in r["kinds"]
    assert c.get("/api/items").status_code == 409
    assert c.get("/api/health").status_code == 200  # health works without a shop


def test_shops_keep_data_separate(make_client):
    c = make_client(with_shop=False)
    tees = c.post("/api/shops", json={"name": "Sora in Bloom", "kind": "clothing"}).json()
    assert tees["slug"] == "sora-in-bloom" and tees["sku_prefix"] == "SIB"
    t = c.post("/api/items", json={"name": "Rhododendron Tee", "size": "M", "quantity": 3}).json()
    assert t["sku"] == f"SIB-{t['id']:05d}-M"

    jewels = c.post("/api/shops", json={"name": "Sora Jewels", "kind": "jewellery",
                                         "sku_prefix": "sj!", "low_stock_default": 5}).json()
    assert jewels["sku_prefix"] == "SJ"
    # creating a shop switches to it
    assert c.get("/api/items").json() == []
    j = c.post("/api/items", json={"name": "Gold hoops", "quantity": 1}).json()
    assert j["sku"].startswith("SJ-") and j["low_stock_threshold"] == 5
    c.post("/api/sales", json={"item_id": j["id"]})

    # switch back: only the tee is there, and its report has no jewellery sale
    c.post(f"/api/shops/{tees['slug']}/select")
    assert [i["name"] for i in c.get("/api/items").json()] == ["Rhododendron Tee"]
    assert c.get("/api/reports/summary").json()["sales_count"] == 0
    # ?shop= overrides the cookie (handy for links and tests)
    assert [i["name"] for i in c.get("/api/items", params={"shop": jewels["slug"]}).json()] == ["Gold hoops"]

    shops = c.get("/api/shops").json()
    assert [s["name"] for s in shops["shops"]] == ["Sora in Bloom", "Sora Jewels"]
    assert shops["current"] == tees["slug"]


def test_same_name_gets_unique_slug(make_client):
    c = make_client(with_shop=False)
    a = c.post("/api/shops", json={"name": "Market Stall"}).json()
    b = c.post("/api/shops", json={"name": "Market Stall"}).json()
    assert a["slug"] == "market-stall" and b["slug"] == "market-stall-2"


def test_update_settings_and_logo(client):
    slug = client.get("/api/shops").json()["current"]
    s = client.patch(f"/api/shops/{slug}", json={"name": "Renamed", "sku_prefix": "rn", "kind": "candle"}).json()
    assert (s["name"], s["sku_prefix"], s["kind"]) == ("Renamed", "RN", "candle")
    assert client.patch(f"/api/shops/{slug}", json={"kind": "spaceships"}).json()["kind"] == "other"

    buf = io.BytesIO()
    Image.new("RGB", (900, 300), (200, 80, 120)).save(buf, "PNG")
    s = client.post(f"/api/shops/{slug}/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")}).json()
    assert s["has_logo"]
    logo = client.get(f"/api/shops/{slug}/logo")
    assert logo.status_code == 200 and Image.open(io.BytesIO(logo.content)).width == 512
    assert client.delete(f"/api/shops/{slug}/logo").json()["has_logo"] is False
    assert client.post("/api/shops/nope/select").status_code == 404


def test_photos_belong_to_their_shop(make_client):
    c = make_client(with_shop=False)
    a = c.post("/api/shops", json={"name": "A"}).json()
    name = c.post("/api/scan", files={"file": ("p.jpg", photo(), "image/jpeg")}).json()["image_path"]
    assert c.get(f"/images/{name}").status_code == 200
    c.post("/api/shops", json={"name": "B"})
    assert c.get(f"/images/{name}").status_code == 404           # not visible from shop B
    assert c.get(f"/images/{name}", params={"shop": a["slug"]}).status_code == 200
    sneaky = c.get("/images/..%2Fshop.json")                       # no path tricks
    assert '"slug"' not in sneaky.text
