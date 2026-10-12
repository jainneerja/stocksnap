"""Scene templates: a real product photo put into a seller's own scene."""

import io
import zipfile

import numpy as np
from PIL import Image, ImageDraw


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def scene_image() -> Image.Image:
    """Cream table, a pink 'old dress' with green dots, a gold figure on it."""
    img = Image.new("RGB", (600, 700), (238, 228, 210))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 300, 540, 620), fill=(225, 40, 140))
    for x in range(100, 520, 60):
        for y in range(340, 600, 50):
            d.ellipse((x, y, x + 14, y + 14), fill=(40, 150, 60))
    d.ellipse((250, 140, 350, 240), fill=(200, 160, 50))   # head
    d.rectangle((265, 240, 335, 330), fill=(225, 40, 140))  # old top
    d.rectangle((230, 300, 250, 420), fill=(200, 160, 50))  # arm
    return img


def product_photo() -> bytes:
    img = Image.new("RGB", (500, 500), (5, 5, 5))
    ImageDraw.Draw(img).ellipse((30, 30, 470, 470), fill=(30, 70, 200))
    return _jpeg(img)


def _client(make_client):
    c = make_client()
    c.app.state.lab.cutter.engine = "basic"  # no model download in tests
    return c


def _make_scene(c):
    r = c.post("/api/scenes", files={"file": ("s.jpg", _jpeg(scene_image()), "image/jpeg")}, data={"name": "Mandir"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    t = c.put(f"/api/scenes/{sid}", json={"cx": 0.5, "top": 300 / 700, "bottom": 620 / 700, "rx": 0.4,
                                          "top_box": [265 / 600, 240 / 700, 335 / 600, 330 / 700]}).json()
    return sid, t


def test_scene_create_adjust_and_files(make_client):
    c = _client(make_client)
    sid, t = _make_scene(c)
    assert t["name"] == "Mandir" and t["width"] == 600 and t["top_box"]
    assert [s["id"] for s in c.get("/api/scenes").json()] == [sid]
    for f in ("scene.jpg", "layers.jpg", "thumb.jpg"):
        assert c.get(f"/api/scenes/{sid}/files/{f}").status_code == 200
    assert c.get(f"/api/scenes/{sid}/files/template.json").status_code == 404
    assert c.put(f"/api/scenes/{sid}", json={"top_box": [0.5, 0.5, 0.4, 0.6]}).status_code == 400
    assert c.put(f"/api/scenes/{sid}", json={"top_box": []}).json()["top_box"] is None
    assert c.get("/api/scenes/zzz").status_code == 404


def test_product_replaces_old_one_and_figure_stays(make_client):
    c = _client(make_client)
    sid, _ = _make_scene(c)
    # keep the arm with one brush stroke (it is the same gold as nothing else here, but test the brush)
    c.put(f"/api/scenes/{sid}", json={"keep": [{"points": [[240 / 600, 310 / 700], [240 / 600, 410 / 700]], "r": 0.02}]})
    r = c.post(f"/api/scenes/{sid}/try", files={"file": ("p.jpg", product_photo(), "image/jpeg")})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    out = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(int)
    blue = (out[:, :, 2] > 150) & (out[:, :, 0] < 90)
    pink = (out[:, :, 0] > 190) & (out[:, :, 1] < 90) & (out[:, :, 2] > 100)
    assert blue[450:560, 150:450].mean() > 0.9      # new product lies in the oval
    assert pink.mean() < 0.01                       # the old dress is gone
    head = out[160:220, 270:330]
    assert abs(head[..., 0].mean() - 200) < 20 and abs(head[..., 2].mean() - 50) < 25   # figure untouched
    arm = out[330:400, 235:246]
    assert abs(arm[..., 0].mean() - 200) < 30     # kept by the brush


def test_listing_photos_for_saved_items(make_client):
    c = _client(make_client)
    sid, _ = _make_scene(c)
    ids = []
    for name in ("Blue Dress", "Blue Dress Two"):
        path = c.post("/api/photos", files={"file": ("p.jpg", product_photo(), "image/jpeg")}).json()["image_path"]
        it = c.post("/api/items", json={"name": name, "price_cents": 1500, "quantity": 2, "image_path": path}).json()
        ids.append((it["id"], it["sku"]))
    job = c.post("/api/listing-photos", json={"items": [{"item_id": ids[0][0], "scene_ids": [sid]},
                                                        {"item_id": ids[1][0], "scene_ids": []}],
                                              "white": True}).json()
    job = c.get(f"/api/listing-photos/{job['id']}").json()
    assert job["status"] == "done" and job["done"] == 2 and not job["notes"]
    assert [o["label"] for o in job["outputs"]] == ["Main (white)", "Mandir", "Main (white)"]
    assert c.get(f"/api/listing-photos/{job['id']}/files/{job['outputs'][1]['file']}").status_code == 200
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/listing-photos/{job['id']}/zip").content))
    sku = ids[0][1]
    assert sorted(z.namelist())[:2] == sorted([f"{sku}/{sku}.MAIN.jpg", f"{sku}/{sku}.PT01.jpg"])
    assert len(z.namelist()) == 3
    # bad requests
    assert c.post("/api/listing-photos", json={"items": [{"item_id": 999}]}).status_code == 404
    assert c.post("/api/listing-photos", json={"items": [{"item_id": ids[0][0], "scene_ids": ["abcdef1234"]}]}).status_code == 404
    assert c.post("/api/listing-photos", json={"items": [{"item_id": ids[0][0]}], "white": False}).status_code == 400


def test_scenes_are_per_shop(make_client):
    c = _client(make_client)
    _make_scene(c)
    c.post("/api/shops", json={"name": "Other shop"})
    assert c.get("/api/scenes").json() == []


def test_auto_setup_from_text(make_client):
    c = _client(make_client)
    r = c.post("/api/scenes", files={"file": ("s.jpg", _jpeg(scene_image()), "image/jpeg")}, data={"name": "Auto"})
    sid = r.json()["id"]
    W, H = 600, 700
    f = lambda x0, y0, x1, y1: [x0 / W, y0 / H, x1 / W, y1 / H]
    c.vision.boxes = {
        "dress": [f(60, 300, 540, 620)],
        "top part of the dress on the chest": [f(262, 225, 338, 332)],
        "face": [f(250, 140, 350, 240)],
        "arm": [f(226, 296, 254, 424)],
    }
    out = c.post(f"/api/scenes/{sid}/auto", json={"product": "Dress", "keep": "arm, ball"}).json()
    t = out["scene"]
    assert "Not found: ball" in " ".join(out["notes"])
    assert abs(t["cx"] - 0.5) < 0.01 and abs(t["top"] - 300 / H) < 0.01 and abs(t["rx"] - 0.4) < 0.01
    assert t["top_box"][1] >= 240 / H - 1e-6          # neckline never above the chin
    assert len(t["keep_outlines"]) == 1 and len(t["keep_outlines"][0]) >= 3
    assert c.vision.located[-1][:3] == ["dress", "top part of the dress on the chest", "face"]
    # and the result: arm kept, old pink gone, figure untouched
    img = c.post(f"/api/scenes/{sid}/try", files={"file": ("p.jpg", product_photo(), "image/jpeg")})
    o = np.asarray(Image.open(io.BytesIO(img.content)).convert("RGB")).astype(int)
    pink = (o[:, :, 0] > 190) & (o[:, :, 1] < 90) & (o[:, :, 2] > 100)
    assert pink.mean() < 0.01
    assert abs(o[330:400, 235:246, 0].mean() - 200) < 35
    assert abs(o[160:220, 270:330, 0].mean() - 200) < 20


def test_auto_setup_needs_the_ai(make_client):
    c = make_client(vision_fails=True)
    c.app.state.lab.cutter.engine = "basic"
    sid = c.post("/api/scenes", files={"file": ("s.jpg", _jpeg(scene_image()), "image/jpeg")}).json()["id"]
    assert c.post(f"/api/scenes/{sid}/auto", json={}).status_code == 503
