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
  "brand": "brand or maker name printed on the product or its label, or empty string if none is visible",
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
    brand: str = ""
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
        brand="" if s("brand", 60).lower() in _NO_VALUE else s("brand", 60),
        price_cents=_price_to_cents(data.get("price")),
        tags=tags,
    )
    if not draft.name and draft.category:
        draft.name = draft.category
    return draft


# Fast mode: the model only answers a few short facts and a template writes the
# listing. On a CPU most of the time goes into generating words, so asking for
# ~30 words instead of ~150 is what makes this several times faster.
FACTS_PROMPT = """Look at the product photo. If there is a second photo, it is a close-up of its label or tag.
Reply with JSON only, short values, using exactly these keys:
{"type": "what the item is, 1-3 words",
 "colours": ["main colours, at most 3"],
 "pattern": "main design or decoration in at most 6 words, or empty",
 "material": "only if obvious, else empty",
 "text": "product name or brand printed on it, else empty",
 "size": "size printed on a label or tag, else empty",
 "price": "price printed on a tag as a number, else empty"}"""


@dataclass
class Facts:
    type: str = ""
    colours: list[str] = field(default_factory=list)
    pattern: str = ""
    material: str = ""
    text: str = ""
    size: str = ""
    price_cents: Optional[int] = None


def parse_facts(raw: str) -> Facts:
    match = re.search(r"\{.*\}", raw, re.S)
    data: dict = {}
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
        val = str(val or "").strip()[:limit]
        return "" if val.lower() in _NO_VALUE else val

    colours = data.get("colours") or data.get("colors") or []
    if isinstance(colours, str):
        colours = re.split(r",|/| and ", colours)
    colours = [str(c).strip().lower() for c in colours if str(c).strip()][:3]
    return Facts(
        type=s("type", 40).lower(),
        colours=colours,
        pattern=s("pattern", 60).lower(),
        material=s("material", 60),
        text=s("text", 60),
        size=_clean_size(s("size", 40)),
        price_cents=_price_to_cents(data.get("price")),
    )


def parse_boxes(raw: str, labels: list[str], w: int, h: int) -> dict[str, list[list[float]]]:
    """Model output -> {label: [boxes as fractions]}. Copes with the usual small-model
    quirks: a bare list, 0-1 or 0-1000 coordinates, labels in other words."""
    data: object = None
    m = re.search(r"[\[{].*[\]}]", raw or "", re.S)
    if m:
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            data = None
    items = data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out: dict[str, list[list[float]]] = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        box = it.get("box") or it.get("bbox") or it.get("bbox_2d")
        if not (isinstance(box, list) and len(box) == 4):
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in box)
        except (TypeError, ValueError):
            continue
        top = max(x0, y0, x1, y1)
        if top <= 1.0:
            sx, sy = 1.0, 1.0  # already fractions
        elif top > max(w, h) * 1.05:
            sx = sy = 1000.0  # 0-1000 grid
        else:
            sx, sy = float(w), float(h)
        fx0, fx1 = sorted((x0 / sx, x1 / sx))
        fy0, fy1 = sorted((y0 / sy, y1 / sy))
        fx0, fy0, fx1, fy1 = (min(max(v, 0.0), 1.0) for v in (fx0, fy0, fx1, fy1))
        if fx1 - fx0 < 0.01 or fy1 - fy0 < 0.01:
            continue
        said = str(it.get("label", "")).strip().lower()
        label = next((l for l in labels if l.lower() == said), None) or next(
            (l for l in labels if l.lower() in said or said in l.lower()), None)
        if label:
            out.setdefault(label, []).append([fx0, fy0, fx1, fy1])
    return out


def seller_context(*parts: str) -> str:
    """Join shop-level and item-level notes from the seller, skipping blanks."""
    return " ".join(p.strip().rstrip(".") + "." for p in parts if p and p.strip())


def build_prompt(hint: str = "", seller: str = "", base: str = PROMPT) -> str:
    prompt = base
    if seller:
        # Small vision models guess from shape alone ("round embroidered thing = hat").
        # The seller knows what they sell, so their words decide what the item IS;
        # the photo only adds colour, pattern and details.
        prompt += (
            f"\n\nIMPORTANT - the seller says: {seller}\n"
            "Treat this as true. Use the seller's words for what the item is, in the name and the "
            "description, even if it looks like something else to you. Only describe what you can see "
            "(colours, pattern, embellishments, shape) on top of that. Do not contradict the seller."
        )
    if hint:
        prompt += f"\n\nAbout this product: {hint}"
    return prompt


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

    def describe(self, images: list[Image.Image], hint: str = "", seller: str = "") -> Draft:
        """images[0] = product photo; optional images[1] = label/tag close-up.
        `hint` adds product-specific guidance (e.g. from a bulk-intake preset);
        `seller` is what the seller says the item is, which wins over the model's guess."""
        payload = {
            "model": self.model,
            "prompt": build_prompt(hint, seller),
            # Tag close-ups keep more pixels so small print stays readable.
            "images": [_to_b64_jpeg(im, 768 if i == 0 else 1024) for i, im in enumerate(images)],
            "format": "json",
            "stream": False,
            # Keep the model in memory between items: on a laptop CPU the first
            # load alone can take a minute.
            "keep_alive": "30m",
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

    def locate(self, image: Image.Image, labels: list[str]) -> dict[str, list[list[float]]]:
        """Find named things in a picture (Qwen2.5-VL can point at objects).
        Returns {label: [[x0, y0, x1, y1], ...]} as fractions of the image."""
        img = image.convert("RGB").copy()
        img.thumbnail((896, 896))
        # Qwen2.5-VL works on a grid of 28 px; give it exactly that so its pixel
        # coordinates line up with ours
        w, h = max(28, img.width // 28 * 28), max(28, img.height // 28 * 28)
        img = img.resize((w, h))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        prompt = (
            f"The image is {w} pixels wide and {h} pixels tall. Find each of these in it: "
            + "; ".join(f'"{l}"' for l in labels)
            + ". Reply with JSON only: {\"items\": [{\"label\": \"<one of the names above>\", "
            "\"box\": [x1, y1, x2, y2]}]} with pixel coordinates. Give one item per object "
            "(two hands = two items). Leave out anything you cannot see."
        )
        payload = {"model": self.model, "prompt": prompt, "images": [base64.b64encode(buf.getvalue()).decode()],
                   "format": "json", "stream": False, "keep_alive": "30m",
                   "options": {"temperature": 0, "num_predict": 400}}
        try:
            r = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("vision model call failed: %s", exc)
            raise VisionUnavailable(str(exc)) from exc
        return parse_boxes(r.json().get("response", ""), labels, w, h)

    def facts(self, images: list[Image.Image], hint: str = "", seller: str = "") -> Facts:
        """Fast mode: a few short facts only (see FACTS_PROMPT)."""
        payload = {
            "model": self.model,
            "prompt": build_prompt(hint, seller, FACTS_PROMPT),
            # smaller pictures: colours and type don't need fine detail; tags keep more
            "images": [_to_b64_jpeg(im, 512 if i == 0 else 896) for i, im in enumerate(images)],
            "format": "json",
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.1, "num_predict": 120},
        }
        try:
            r = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("vision model call failed: %s", exc)
            raise VisionUnavailable(str(exc)) from exc
        return parse_facts(r.json().get("response", ""))
