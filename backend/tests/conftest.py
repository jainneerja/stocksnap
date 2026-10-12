import io
import os
import tempfile

# Keep the module-level app in main.py away from the real ~/.stocksnap
os.environ.setdefault("STOCKSNAP_DATA_DIR", tempfile.mkdtemp(prefix="stocksnap-import-"))
os.environ.setdefault("STOCKSNAP_MATCHER", "lite")

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import Settings
from app.main import create_app
from app.services.ai import AI
from app.services.matcher import LiteEmbedder
from app.services.vision import Draft, Facts, VisionUnavailable


class FakeVision:
    """Stands in for Ollama so tests are fast and deterministic."""

    model = "fake"

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[int] = []  # number of images per call
        self.hints: list[str] = []
        self.sellers: list[str] = []
        self.fact_calls = 0
        self.boxes = {}
        self.located = []
        self.pattern = "floral print"
        self.read_text = False
        self.label_reader = None  # optional fn(img, hint) -> Draft, set by tests

    def status(self):
        return {"available": not self.fail, "model": self.model, "detail": "fake"}

    def locate(self, image, labels):
        """Pretend to find things: tests set self.boxes = {label: [[x0,y0,x1,y1], ...]}."""
        if self.fail:
            raise VisionUnavailable("down")
        self.located.append(list(labels))
        return {k: v for k, v in self.boxes.items() if k in labels}

    def facts(self, images, hint="", seller=""):
        """Fast mode: derived from the same fake so tests stay simple."""
        d = self.describe(images, hint, seller)
        self.fact_calls += 1
        return Facts(type=d.category.lower(), colours=[c for c in [d.color.lower()] if c],
                     pattern=self.pattern, text=d.name if self.read_text else "", size=d.size,
                     price_cents=d.price_cents)

    def describe(self, images, hint="", seller=""):
        if self.fail:
            raise VisionUnavailable("down")
        self.calls.append(len(images))
        self.hints.append(hint)
        self.sellers.append(seller)
        if self.label_reader:
            return self.label_reader(images[0], hint)
        has_tag = len(images) > 1
        return Draft(
            name="Rhododendron Tee",
            category="T-shirt",
            description="Soft organic cotton tee with a hand-drawn rhododendron.",
            color="pink",
            material="cotton",
            size="M" if has_tag else "",
            price_cents=2800 if has_tag else None,
            tags=["washington", "floral", "tee"],
        )


@pytest.fixture
def make_client(tmp_path):
    def _make(vision_fails: bool = False, with_shop: bool = True):
        settings = Settings(data_dir=tmp_path / "data", matcher="lite", match_threshold=0.9)
        ai = AI(vision=FakeVision(vision_fails), embedder=LiteEmbedder(), match_threshold=0.9)
        c = TestClient(create_app(settings, ai))
        c.vision = ai.vision
        if with_shop:
            r = c.post("/api/shops", json={"name": "Test Shop", "kind": "other", "sku_prefix": "",
                                             "describe_mode": "full"})
            assert r.status_code == 201, r.text  # also selects it (cookie)
        return c

    return _make


@pytest.fixture
def client(make_client):
    return make_client()


def photo(color=(220, 60, 120), shape="circle") -> bytes:
    img = Image.new("RGB", (400, 300), (245, 245, 240))
    d = ImageDraw.Draw(img)
    if shape == "circle":
        d.ellipse((120, 60, 280, 240), fill=color)
    else:
        d.rectangle((60, 100, 340, 200), fill=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def barcode_photo(text: str) -> bytes:
    import zxingcpp

    code = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.EAN13)
    img = zxingcpp.write_barcode_to_image(code, scale=4)
    pil = Image.fromarray(__import__("numpy").asarray(img)).convert("RGB")
    canvas = Image.new("RGB", (pil.width + 80, pil.height + 80), "white")
    canvas.paste(pil, (40, 40))
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()
