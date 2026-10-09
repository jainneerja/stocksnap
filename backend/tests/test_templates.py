"""Template descriptions: instant (pixels + seller info), fast (short AI facts), full."""

import io

from PIL import Image, ImageDraw

from app.services.listing import colour_names, fill
from test_bulk import upload
from trays import jewellery_tray


def dress_photo() -> bytes:
    """Red round 'dress' with pink flowers on a black cloth."""
    img = Image.new("RGB", (400, 400), (8, 8, 8))
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 360, 360), fill=(185, 25, 35))
    for x, y in [(110, 110), (290, 110), (110, 290), (290, 290), (200, 70), (200, 330)]:
        d.ellipse((x - 38, y - 38, x + 38, y + 38), fill=(235, 120, 175))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _photo(client):
    return client.post("/api/photos", files={"file": ("d.jpg", dress_photo(), "image/jpeg")}).json()["image_path"]


def _shop(client, **changes):
    slug = client.get("/api/shops").json()["current"]
    r = client.patch(f"/api/shops/{slug}", json=changes)
    assert r.status_code == 200, r.text
    return r.json()


def test_colours_from_pixels_ignore_background():
    img = Image.open(io.BytesIO(dress_photo()))
    assert colour_names(img) == ["red", "pink"]


def test_optional_parts_drop_out_and_sentences_are_capitalised():
    t = "{colour} {type}[ with {pattern}][ in {material}]. [Size {size}. ]From {shop}."
    assert fill(t, {"colour": "red", "type": "dress", "shop": "Gopal Shringar"}) == "Red dress. From Gopal Shringar."
    assert fill(t, {"colour": "red", "type": "dress", "pattern": "flowers", "size": "3", "shop": "X"}) \
        == "Red dress with flowers. Size 3. From X."


def test_instant_mode_needs_no_ai(client):
    _shop(client, describe_mode="instant", name="Gopal Shringar", kind="clothing")
    r = client.post("/api/describe", json={"image_path": _photo(client), "hint": "embroidered outfit"}).json()
    assert r["mode"] == "instant" and client.vision.calls == []
    assert r["name"] == "Red and pink embroidered outfit"
    assert r["description"].endswith("Made with care by Gopal Shringar.")
    assert r["color"] == "red and pink" and r["seconds"] < 2


def test_fast_mode_asks_ai_for_facts_and_uses_the_template(client):
    _shop(client, describe_mode="fast", name="Gopal Shringar", kind="clothing")
    r = client.post("/api/describe", json={"image_path": _photo(client)}).json()
    assert r["mode"] == "fast" and client.vision.fact_calls == 1
    assert r["name"] == "Pink t-shirt"           # AI facts: type + colour
    assert "with floral print" in r["description"] and "Gopal Shringar" in r["description"]


def test_fast_mode_falls_back_to_instant_when_ai_is_off(make_client):
    c = make_client(vision_fails=True)
    _shop(c, describe_mode="fast", kind="clothing")
    r = c.post("/api/describe", json={"image_path": _photo(c)})
    assert r.status_code == 200 and r.json()["mode"] == "instant"
    assert r.json()["name"] == "Red and pink outfit"


def test_custom_templates_and_preview(client):
    info = _shop(client, describe_mode="instant", name="Bloom", kind="clothing",
                 name_template="{type} - {colour}", desc_template="Lovely {colour} {type}[, size {size}]. By {shop}.")
    assert info["name_template"] == "{type} - {colour}"
    r = client.post("/api/describe", json={"image_path": _photo(client), "hint": "dress"}).json()
    assert r["name"] == "Dress - red and pink"
    assert r["description"] == "Lovely red and pink dress. By Bloom."
    p = client.post("/api/shops/preview-description", json={"kind": "jewellery", "name": "Sora"}).json()
    assert p["name"] and "Sora" in p["description"] and "{colour}" in p["default_name_template"]
    # bad mode falls back to fast
    assert _shop(client, describe_mode="turbo")["describe_mode"] == "fast"


def test_bulk_instant_uses_batch_answers_and_no_ai(client):
    _shop(client, describe_mode="instant", name="Sora", kind="jewellery")
    b = client.post("/api/batches", json={"preset": "jewellery", "answers": {
        "type": "Earrings", "metal": "Gold-plated", "price": "12"}}).json()
    tray, n = jewellery_tray(seed=3, cols=3, rows=1)
    upload(client, b["id"], tray)
    client.post(f"/api/batches/{b['id']}/describe")
    out = client.get(f"/api/batches/{b['id']}").json()
    assert out["status"] == "review" and client.vision.calls == [] and client.vision.fact_calls == 0
    g = [x for x in out["groups"] if x["include"]][0]
    assert g["name"].endswith("earrings") and g["category"] == "Earrings"
    assert g["description"].endswith("A lovely piece from Sora.") and "Gold-plated" in g["description"]
    assert g["price_cents"] == 1200


def test_bulk_fast_mode_one_short_call_per_item(client):
    _shop(client, describe_mode="fast", name="Sora", kind="jewellery")
    b = client.post("/api/batches", json={"preset": "jewellery", "answers": {}}).json()
    tray, n = jewellery_tray(seed=4, cols=3, rows=1)
    upload(client, b["id"], tray)
    client.post(f"/api/batches/{b['id']}/describe")
    out = client.get(f"/api/batches/{b['id']}").json()
    groups = [x for x in out["groups"] if x["include"]]
    assert client.vision.fact_calls == len(groups)
    assert all("A lovely piece from Sora." in g["description"] for g in groups)
