"""Item description with a local vision-language model served by Ollama.

Default model: qwen2.5vl:3b (Apache-2.0). Lighter option for low-end laptops:
moondream (Apache-2.0). Any Ollama vision model works - set
STOCKSNAP_VISION_MODEL.

Nothing is sent over the internet: Ollama runs on this machine.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx
from PIL import Image

log = logging.getLogger(__name__)

PROMPT = """You help a small handmade-goods seller catalogue products.
The first photo shows the product. If there is a second photo, it is a
close-up of the product's label, hang tag or price sticker.
Describe the single main product for sale. Read any visible text on labels
or tags carefully to find the size and price - do not guess them.
Reply with JSON only, using exactly these keys:
{
  "name": "short product name, max 6 words, without the size",
  "category": "one word or two, e.g. T-shirt, Candle, Mug, Earrings",
  "description": "1-2 friendly sentences a shopper would read",
  "color": "main colour(s)",
  "material": "likely material, or empty string if unsure",
  "size": "size exactly as printed on a label or tag (e.g. M, XL, 2T, 8 oz, 16 in), or empty string if none is visible",
  "price": "price printed on a tag as a number (e.g. 24.00), or empty string if none is visible",
  "tags": ["3 to 6 lowercase keywords"]
}"""


@dataclass
class Draft:
    name: str = ""
    category: str = ""
    description: str = ""
    color: str = ""
    material: str = ""
    size: str = ""
    price_cents: Optional[int] = None  # only when a price tag was readable
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class VisionUnavailable(RuntimeError):
    pass


def _to_b64_jpeg(img: Image.Image, max_px: int = 768) -> str:
    img = img.copy()
    img.thumbnail((max_px, max_px))  # smaller = much faster on CPU
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


_NO_VALUE = {"", "none", "n/a", "na", "null", "unknown", "not visible", "no size", "-"}


def _clean_size(val: str) -> str:
    val = re.sub(r"^\s*size\s*[:\-]?\s*", "", val, flags=re.I).strip(" .")
    return "" if val.lower() in _NO_VALUE else val[:20]


def _price_to_cents(val) -> Optional[int]:
    if isinstance(val, bool) or val is None:
        return None
    if isinstance(val, (int, float)):
        num = float(val)
    else:
        m = re.search(r"\d+(?:[.,]\d{1,2})?", str(val))
        if not m:
            return None
        num = float(m.group(0).replace(",", "."))
    cents = round(num * 100)
    return cents if 0 < cents < 10_000_000 else None


def parse_draft(raw: str) -> Draft:
    """Parse model output defensively - small models don't always obey."""
    match = re.search(r"\{.*\}", raw, re.S)
    data = {}
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}

    def s(key: str, limit: int) -> str:
        val = data.get(key, "")
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)
        return str(val or "").strip()[:limit]

    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = re.split(r"[,;]", tags)
    tags = [str(t).strip().lower() for t in tags if str(t).strip()][:8]

    draft = Draft(
        name=s("name", 80),
        category=s("category", 40),
        description=s("description", 500),
        color=s("color", 60),
        material=s("material", 60),
        size=_clean_size(s("size", 40)),
        price_cents=_price_to_cents(data.get("price")),
        tags=tags,
    )
    if not draft.name and draft.category:
        draft.name = draft.category
    return draft


class OllamaVision:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def status(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=2)
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
            wanted = self.model if ":" in self.model else f"{self.model}:latest"
            installed = wanted in names or self.model in names
            return {
                "available": installed,
                "model": self.model,
                "detail": "ready" if installed else f"run: ollama pull {self.model}",
            }
        except Exception:  # noqa: BLE001
            return {
                "available": False,
                "model": self.model,
                "detail": "Ollama is not running (install from ollama.com, then `ollama serve`)",
            }

    def describe(self, images: list[Image.Image], hint: str = "") -> Draft:
        """images[0] = product photo; optional images[1] = label/tag close-up.
        `hint` adds product-specific guidance (e.g. from a bulk-intake preset)."""
        payload = {
            "model": self.model,
            "prompt": PROMPT + (f"\n\nAbout this product: {hint}" if hint else ""),
            # Tag close-ups keep more pixels so small print stays readable.
            "images": [_to_b64_jpeg(im, 768 if i == 0 else 1024) for i, im in enumerate(images)],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        }
        try:
            r = httpx.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s
            )
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("vision model call failed: %s", exc)
            raise VisionUnavailable(str(exc)) from exc
        return parse_draft(r.json().get("response", ""))
