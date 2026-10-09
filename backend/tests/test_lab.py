import io
import time

from PIL import Image

from app.services import imagelab
from app.services.imagelab import ImageLab
from conftest import photo


class FakeGenerator:
    installed = True
    model = "fake-turbo"

    def __init__(self):
        self._pipe = None
        self.error = ""
        self.prompts = []

    def status(self):
        return {"available": True, "model": self.model, "device": "cpu", "loaded": self._pipe is not None, "detail": "ready"}

    def generate(self, prompt, seed, steps=2):
        self._pipe = object()
        self.prompts.append(prompt)
        return Image.new("RGB", (512, 512), (120 + seed % 50, 90, 60))


def wait(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/lab/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def lab_client(make_client, monkeypatch, with_rembg=False):
    c = make_client()
    lab = ImageLab("isnet-general-use", "fake")
    if not with_rembg:
        lab.cutter.engine = "basic"  # deterministic + fast in tests
    lab.generator = FakeGenerator()
    c.app.state.lab = lab
    return c, lab


def test_status_lists_engines(make_client, monkeypatch):
    c, _ = lab_client(make_client, monkeypatch)
    s = c.get("/api/lab/status").json()
    assert s["cutout"]["engine"] == "basic" and s["generator"]["available"]
    assert "main_white" in s["looks"] and "custom" in s["scenes"]


def test_one_photo_becomes_a_set_of_listing_images(make_client, monkeypatch):
    c, lab = lab_client(make_client, monkeypatch)
    big = Image.open(io.BytesIO(photo())).resize((1600, 1200))
    buf = io.BytesIO()
    big.save(buf, "JPEG")
    r = c.post("/api/lab/jobs", files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")}, data={
        "looks": "main_white,shadow_grey,gradient,tabletop,closeup,card,ai_scene",
        "scene": "custom", "custom_prompt": "soft pink silk", "ai_count": "2",
        "title": "Rose Dress", "bullets": "Pure cotton\nHand embroidered",
    })
    assert r.status_code == 201
    j = wait(c, r.json()["id"])
    assert j["status"] == "done", j["message"]
    labels = [o["label"] for o in j["outputs"]]
    assert labels == ["Main image (white)", "Soft shadow", "Colour backdrop", "Tabletop", "Close-up",
                      "Details card", "AI scene 1", "AI scene 2"]
    assert lab.generator.prompts[0].startswith("soft pink silk") and "no people" in lab.generator.prompts[0]

    main = Image.open(io.BytesIO(c.get(f"/api/lab/files/{j['id']}/{j['outputs'][0]['file']}").content))
    assert main.size == (2000, 2000)
    px = main.convert("RGB")
    assert px.getpixel((5, 5)) == (255, 255, 255) and px.getpixel((1995, 5)) == (255, 255, 255)  # pure white
    # the product fills most of the frame on the main image
    gray = main.convert("L").point(lambda v: 255 if v < 245 else 0)
    x0, y0, x1, y1 = gray.getbbox()
    assert max(x1 - x0, y1 - y0) > 2000 * 0.75

    z = c.get(f"/api/lab/jobs/{j['id']}/zip", params={"prefix": "SIB-00012"})
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names[0] == "SIB-00012.MAIN.jpg" and names[1] == "SIB-00012.PT01.jpg" and len(names) == 8

    assert [x["id"] for x in c.get("/api/lab/jobs").json()] == [j["id"]]
    assert c.delete(f"/api/lab/jobs/{j['id']}").status_code == 204
    assert c.get(f"/api/lab/jobs/{j['id']}").status_code == 404


def test_ai_failure_keeps_other_images(make_client, monkeypatch):
    c, lab = lab_client(make_client, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("no internet")

    lab.generator.generate = boom
    r = c.post("/api/lab/jobs", files={"file": ("p.jpg", photo(), "image/jpeg")},
               data={"looks": "main_white,ai_scene"})
    j = wait(c, r.json()["id"])
    assert j["status"] == "done" and len(j["outputs"]) == 1
    assert any("no internet" in n for n in j["notes"])


def test_bad_inputs(make_client, monkeypatch):
    c, _ = lab_client(make_client, monkeypatch)
    assert c.post("/api/lab/jobs", files={"file": ("x.jpg", b"nope", "image/jpeg")}).status_code == 400
    assert c.post("/api/lab/jobs", files={"file": ("p.jpg", photo(), "image/jpeg")},
                  data={"looks": "bogus"}).status_code == 400
    assert c.get("/api/lab/jobs/not-a-job").status_code == 404
    r = c.post("/api/lab/jobs", files={"file": ("p.jpg", photo(), "image/jpeg")}, data={"looks": "main_white"})
    jid = r.json()["id"]
    assert c.get(f"/api/lab/files/{jid}/job.json").status_code == 404      # only images are served
    sneaky = c.get(f"/api/lab/files/{jid}/..%2F..%2Fshop.json")
    assert '"slug"' not in sneaky.text


def test_jobs_are_per_shop(make_client, monkeypatch):
    c, _ = lab_client(make_client, monkeypatch)
    r = c.post("/api/lab/jobs", files={"file": ("p.jpg", photo(), "image/jpeg")}, data={"looks": "main_white"})
    jid = r.json()["id"]
    c.post("/api/shops", json={"name": "Other shop"})
    assert c.get(f"/api/lab/jobs/{jid}").status_code == 404


def test_dominant_colour_ignores_white():
    cut = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    for x in range(20, 80):
        for y in range(20, 80):
            cut.putpixel((x, y), (200, 30, 60, 255) if y < 60 else (250, 250, 250, 255))
    r, g, b = imagelab.dominant_color(cut)
    assert r > 150 and g < 80
