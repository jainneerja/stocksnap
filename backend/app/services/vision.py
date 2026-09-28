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

import httpx
from PIL import Image

log = logging.getLogger(__name__)

PROMPT = """You help a small handmade-goods seller catalogue products.
Look at the photo and describe the single main product for sale.
Reply with JSON only, using exactly these keys:
{
  "name": "short product name, max 6 words",
  "category": "one word or two, e.g. T-shirt, Candle, Mug, Earrings",
  "description": "1-2 friendly sentences a shopper would read",
  "color": "main colour(s)",
  "material": "likely material, or empty string if unsure",
  "tags": ["3 to 6 lowercase keywords"]
}"""


@dataclass
class Draft:
    name: str = ""
    category: str = ""
    description: str = ""
    color: str = ""
    material: str = ""
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

    def describe(self, img: Image.Image) -> Draft:
        payload = {
            "model": self.model,
            "prompt": PROMPT,
            "images": [_to_b64_jpeg(img)],
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
