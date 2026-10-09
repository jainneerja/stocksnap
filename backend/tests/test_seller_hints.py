"""The seller can tell the AI what their items are (shop-wide, per batch, per photo)."""

import io

from PIL import Image

from app.services.vision import Draft, build_prompt, seller_context
from test_bulk import upload
from trays import jewellery_tray


def _jpeg(color=(200, 40, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, "JPEG")
    return buf.getvalue()


def test_prompt_puts_seller_words_first_and_firmly():
    p = build_prompt(hint="ONE piece of jewellery.", seller="Dresses for small statues.")
    assert "the seller says: Dresses for small statues." in p
    assert "Do not contradict the seller" in p
    assert p.index("seller says") < p.index("About this product")
    assert "seller says" not in build_prompt()
    assert seller_context("", "  doll outfits ", "size 3.") == "doll outfits. size 3."


def test_shop_context_saved_and_editable(client):
    shops = client.get("/api/shops").json()
    slug = shops["current"]
    r = client.patch(f"/api/shops/{slug}", json={"ai_context": "Handmade outfits for small figurines"})
    assert r.json()["ai_context"] == "Handmade outfits for small figurines"
    assert client.patch(f"/api/shops/{slug}", json={"ai_context": ""}).json()["ai_context"] == ""
    r = client.post("/api/shops", json={"name": "Second", "ai_context": "Pet bandanas"})
    assert r.json()["ai_context"] == "Pet bandanas"


def test_add_page_passes_shop_context_and_hint(client):
    slug = client.get("/api/shops").json()["current"]
    client.patch(f"/api/shops/{slug}", json={"ai_context": "Outfits for figurines"})
    path = client.post("/api/photos", files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).json()["image_path"]
    assert client.post("/api/describe", json={"image_path": path, "hint": "a crown"}).status_code == 200
    assert client.vision.sellers[-1] == "Outfits for figurines. a crown."
    client.post("/api/describe", json={"image_path": path})
    assert client.vision.sellers[-1] == "Outfits for figurines."


def test_batch_note_reaches_ai_but_not_items(client):
    slug = client.get("/api/shops").json()["current"]
    client.patch(f"/api/shops/{slug}", json={"ai_context": "Outfits for figurines"})
    client.vision.label_reader = lambda img, hint: Draft(name="Embroidered Hat", category="Hat", description="A hat.")
    b = client.post("/api/batches", json={"preset": "jewellery", "answers": {"about": "round dresses", "price": "15"}}).json()
    tray, n = jewellery_tray(seed=1, cols=3, rows=1)
    upload(client, b["id"], tray)
    client.post(f"/api/batches/{b['id']}/describe")
    assert client.vision.sellers[-1] == "Outfits for figurines. round dresses."
    out = client.get(f"/api/batches/{b['id']}").json()
    g = out["groups"][0]
    assert g["name"] == "Embroidered Hat" and g["price_cents"] == 1500

    # Redo with a better note: AI text is cleared and rewritten, price kept.
    client.patch(f"/api/batches/{b['id']}/groups/{g['id']}", json={"price_cents": 1900})
    client.vision.label_reader = lambda img, hint: Draft(name="Round Embroidered Dress", category="Other", description="A dress.")
    out = client.post(f"/api/batches/{b['id']}/describe", json={"redo": True, "note": "Round dresses for figurines"}).json()
    out = client.get(f"/api/batches/{b['id']}").json()
    assert out["answers"]["about"] == "Round dresses for figurines"
    assert out["status"] == "review"
    assert all(x["name"] == "Round Embroidered Dress" for x in out["groups"] if x["include"])
    assert next(x for x in out["groups"] if x["id"] == g["id"])["price_cents"] == 1900
    assert client.vision.sellers[-1].endswith("Round dresses for figurines.")

    items = client.post(f"/api/batches/{b['id']}/save").json()
    assert items and "figurines" not in (items[0].get("attributes") or "")
