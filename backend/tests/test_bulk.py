import numpy as np

from app.services.vision import Draft
from trays import SOAPS, jewellery_tray, soap_tray


def soap_reader(img, hint):
    """Fake label reading: pick the soap whose colour matches the crop."""
    px = np.asarray(img.convert("RGB")).reshape(-1, 3).astype(int)
    noise = [(238, 236, 230), (250, 250, 245), (205, 203, 198)]  # background, label, shadow
    keep = np.all([np.abs(px - np.array(c)).sum(axis=1) > 40 for c in noise], axis=0)
    col = np.median(px[keep], axis=0)
    name, _ = min(SOAPS, key=lambda s: np.abs(np.array(s[1]) - col).sum())
    return Draft(name=f"{name.title()} Soap", category="Bar soap", description=f"{name.title()} cold-process soap.",
                 size="4 oz", tags=["soap", name.lower()])


def jewel_reader(img, hint):
    r, g, b = np.asarray(img.convert("RGB")).reshape(-1, 3).max(axis=0)
    tone = "Gold-tone" if r > 200 and b < 120 else "Silver-tone"
    return Draft(name=f"{tone} piece", category="Earrings", description="A pretty piece.",
                 material="should be ignored", tags=["jewellery"])


def upload(client, batch_id, data):
    r = client.post(f"/api/batches/{batch_id}/photos", files={"file": ("tray.jpg", data, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def test_presets_listed(client):
    presets = {p["key"]: p for p in client.get("/api/presets").json()}
    assert presets["jewellery"]["mode"] == "unique" and presets["soap"]["mode"] == "identical"
    assert any(q["key"] == "metal" for q in presets["jewellery"]["questions"])
    assert "black" in presets["jewellery"]["background"].lower()


def test_jewellery_batch_counts_ids_and_describes_every_piece(client):
    client.vision.label_reader = jewel_reader
    b = client.post("/api/batches", json={"preset": "jewellery", "answers": {
        "metal": "Sterling silver (925)", "stones": "Cubic zirconia", "price": "18", "cost": "4.50"}}).json()

    tray1, n1 = jewellery_tray(seed=1)
    out = upload(client, b["id"], tray1)
    assert out["progress"]["pieces"] == n1 == 24
    assert out["photos"][0]["detections"][0]["number"] == 1

    tray2, n2 = jewellery_tray(seed=2, cols=4, rows=3)
    out = upload(client, b["id"], tray2)
    nums = [d["number"] for d in out["photos"][1]["detections"]]
    assert nums == list(range(25, 25 + n2))           # numbering continues across photos
    assert out["progress"]["groups"] == 24 + n2        # one-of-a-kind: every piece is its own item

    # tap a false detection to drop it
    drop = out["photos"][1]["detections"][0]["id"]
    out = client.patch(f"/api/batches/{b['id']}/detections/{drop}", json={"include": False}).json()
    assert out["progress"]["pieces"] == 24 + n2 - 1

    out = client.post(f"/api/batches/{b['id']}/describe").json()  # TestClient runs the background task
    out = client.get(f"/api/batches/{b['id']}").json()
    assert out["status"] == "review" and out["progress"]["done"] == out["progress"]["groups"]
    g = out["groups"][0]
    assert g["material"] == "Sterling silver (925)"   # seller's answer beats the AI
    assert g["name"].endswith("piece") and g["price_cents"] == 1800 and g["cost_cents"] == 450
    assert "Sterling silver" in client.vision.hints[-1]  # answers are given to the AI as context

    # bulk price: all earrings $20
    out = client.post(f"/api/batches/{b['id']}/bulk-edit", json={"price_cents": 2000, "category": "earrings"}).json()
    assert all(g["price_cents"] == 2000 for g in out["groups"] if g["include"])

    items = client.post(f"/api/batches/{b['id']}/save").json()
    assert len(items) == 24 + n2 - 1
    assert len({i["sku"] for i in items}) == len(items)   # unique IDs
    assert items[0]["sku"].startswith("EAR-") and all(i["quantity"] == 1 for i in items)
    assert '"Stones": "Cubic zirconia"' in items[0]["attributes"]

    svg = client.get(f"/api/items/{items[0]['id']}/barcode.svg")
    assert svg.status_code == 200 and "<svg" in svg.text

    stock = client.get("/api/reports/stock").json()
    assert stock["totals"]["added"] == len(items)

    # saving again does nothing; discarding a saved batch is refused
    assert client.post(f"/api/batches/{b['id']}/save").json() == []
    assert client.delete(f"/api/batches/{b['id']}").status_code == 409


def test_soap_batch_groups_identical_bars_and_restocks_existing(client):
    client.vision.label_reader = soap_reader
    # Lavender soap 4 oz already in stock
    existing = client.post("/api/items", json={"name": "Lavender Soap", "size": "4 oz", "quantity": 2,
                                               "cost_cents": 200, "price_cents": 700}).json()

    b = client.post("/api/batches", json={"preset": "soap", "answers": {"cost": "2", "price": "7"}}).json()
    layout = [0, 0, 1, 2, 0, 1, 1, 0, 2, 2, 0, 1]   # 5 lavender, 4 oatmeal, 3 charcoal
    out = upload(client, b["id"], soap_tray(layout))
    assert out["progress"]["pieces"] == 12 and out["progress"]["groups"] == 3

    # second tray, shot differently: 2 more oatmeal. They may look different enough to
    # start a new group - reading the label afterwards merges them.
    out = upload(client, b["id"], soap_tray([1, 1], seed=5))
    assert out["progress"]["units"] == 14

    client.post(f"/api/batches/{b['id']}/describe")
    out = client.get(f"/api/batches/{b['id']}").json()
    groups = {g["name"]: g for g in out["groups"]}
    assert {k: g["count"] for k, g in groups.items()} == {"Lavender Soap": 5, "Oatmeal Soap": 6, "Charcoal Soap": 3}
    assert len(out["groups"]) == 3
    assert len(client.vision.calls) <= 4                     # one AI call per look-alike group, not per bar
    assert groups["Lavender Soap"]["existing_item"]["id"] == existing["id"]

    # a carton of charcoal the camera couldn't count
    gid = groups["Charcoal Soap"]["id"]
    out = client.patch(f"/api/batches/{b['id']}/groups/{gid}", json={"count_override": 24}).json()
    assert {g["name"]: g["count"] for g in out["groups"]}["Charcoal Soap"] == 24

    items = {i["name"]: i for i in client.post(f"/api/batches/{b['id']}/save").json()}
    assert items["Lavender Soap"]["id"] == existing["id"] and items["Lavender Soap"]["quantity"] == 2 + 5
    assert items["Oatmeal Soap"]["quantity"] == 6 and items["Charcoal Soap"]["quantity"] == 24
    assert items["Oatmeal Soap"]["sku"].startswith("BAR-") and items["Oatmeal Soap"]["size"] == "4 oz"

    stock = {r["name"]: r for r in client.get("/api/reports/stock").json()["rows"]}
    assert stock["Lavender Soap"]["added"] == 7 and stock["Lavender Soap"]["closing"] == 7


def test_ai_down_still_lets_you_save(make_client):
    c = make_client(vision_fails=True)
    b = c.post("/api/batches", json={"preset": "jewellery", "answers": {}}).json()
    data, n = jewellery_tray(seed=4, cols=3, rows=2)
    upload(c, b["id"], data)
    c.post(f"/api/batches/{b['id']}/describe")
    out = c.get(f"/api/batches/{b['id']}").json()
    assert out["progress"]["failed"] == n
    gid = out["groups"][0]["id"]
    out = c.patch(f"/api/batches/{b['id']}/groups/{gid}", json={"name": "Silver hoops"}).json()
    assert out["groups"][0]["status"] == "done"
    items = c.post(f"/api/batches/{b['id']}/save").json()
    assert len(items) == n and items[0]["name"] == "Silver hoops"
    assert items[1]["name"].startswith("Jewellery #")


def test_blank_photo_warns(client):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (15, 15, 15)).save(buf, "JPEG")
    b = client.post("/api/batches", json={"preset": "other"}).json()
    out = upload(client, b["id"], buf.getvalue())
    assert out["progress"]["pieces"] == 0 and "No items found" in out["warning"]
    assert client.delete(f"/api/batches/{b['id']}").status_code == 204


def test_unknown_preset(client):
    assert client.post("/api/batches", json={"preset": "spaceships"}).status_code == 400


def test_bulk_categories_come_from_a_fixed_list(client):
    def reader(img, hint):
        assert "MUST be one of" in hint and "Pins & Brooches" in hint
        return Draft(name="Anchor brooch", category="brooch", description="x")

    client.vision.label_reader = reader
    b = client.post("/api/batches", json={"preset": "jewellery", "answers": {}}).json()
    data, n = jewellery_tray(seed=4, cols=3, rows=1)
    upload(client, b["id"], data)
    client.post(f"/api/batches/{b['id']}/describe")
    out = client.get(f"/api/batches/{b['id']}").json()
    assert {g["category"] for g in out["groups"]} == {"Pins & Brooches"}
    items = client.post(f"/api/batches/{b['id']}/save").json()
    assert items[0]["sku"].startswith("PIN-")

    # batch filter + facet
    f = client.get("/api/items/facets").json()
    assert f["batches"][0]["id"] == b["id"] and f["batches"][0]["items"] == n
    assert len(client.get("/api/items", params={"batch_id": b["id"]}).json()) == n
