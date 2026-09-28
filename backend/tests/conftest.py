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
from app.services.vision import Draft, VisionUnavailable


class FakeVision:
    """Stands in for Ollama so tests are fast and deterministic."""

    model = "fake"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def status(self):
        return {"available": not self.fail, "model": self.model, "detail": "fake"}

    def describe(self, img):
        if self.fail:
            raise VisionUnavailable("down")
        return Draft(
            name="Rhododendron Tee",
            category="T-shirt",
            description="Soft organic cotton tee with a hand-drawn rhododendron.",
            color="pink",
            material="cotton",
            tags=["washington", "floral", "tee"],
        )


@pytest.fixture
def make_client(tmp_path):
    def _make(vision_fails: bool = False):
        settings = Settings(data_dir=tmp_path / "data", matcher="lite", match_threshold=0.9)
        ai = AI(vision=FakeVision(vision_fails), embedder=LiteEmbedder(), match_threshold=0.9)
        return TestClient(create_app(settings, ai))

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
