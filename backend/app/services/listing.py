"""Item names and descriptions from templates.

Three speeds, chosen per shop (Shop settings -> Item descriptions):

  instant  no AI at all: colours are read from the photo's pixels, the item
           type comes from what the seller told us (batch answers / "What is
           it?"), and the shop's template writes the text. Well under a second.
  fast     the vision model answers a handful of short facts (type, colours,
           pattern, printed text); the template writes the text. Several times
           quicker than free writing on a CPU, and every listing reads in the
           shop's own style.
  full     the model writes name, description and tags freely (slowest).

Templates use {placeholders}; anything in [square brackets] is dropped when a
placeholder inside it is empty, so "[ in {material}]" disappears if the
material is unknown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image

from .vision import Draft, Facts

MODES = ("instant", "fast", "full")
PLACEHOLDERS = ("type", "colour", "pattern", "material", "size", "brand", "text", "shop")

# name / description templates per shop type
DEFAULT_TEMPLATES: dict[str, tuple[str, str]] = {
    "clothing": ("{colour} {type}",
                 "{colour} {type}[ with {pattern}][ in {material}]. [Size {size}. ]Made with care by {shop}."),
    "jewellery": ("{colour} {type}",
                  "{colour} {type}[ with {pattern}][, {material}]. A lovely piece from {shop}."),
    "soap": ("[{text}]",
             "{type}[: {text}][, {size}][ - {pattern}]. Handmade by {shop}."),
    "candle": ("[{text}]",
               "{colour} {type}[: {text}][, {size}]. Hand-poured by {shop}."),
    "other": ("{colour} {type}",
              "{colour} {type}[ with {pattern}][ in {material}]. [Size {size}. ]From {shop}."),
}

def _name_hsv(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Plain colour word per pixel from hue/saturation/value (h 0-360, s/v 0-1).
    Hue rules cope with shading better than nearest-RGB: a red dress in shadow
    is still red, not brown."""
    out = np.empty(h.shape, dtype=object)
    out[:] = "grey"
    grey = s < 0.18
    out[grey & (v > 0.85)] = "white"
    out[grey & (v <= 0.85) & (v > 0.6)] = "silver"
    warm_pale = (s >= 0.1) & (s < 0.32) & (h >= 20) & (h < 55) & (v > 0.7)
    out[warm_pale] = "cream"
    c = ~grey & ~warm_pale
    red = c & ((h < 12) | (h >= 345))
    out[red] = "red"
    out[red & (v < 0.38)] = "maroon"
    o = c & (h >= 12) & (h < 35)
    out[o] = "orange"
    out[o & (v < 0.55)] = "brown"
    out[o & (s < 0.45) & (v >= 0.55)] = "beige"
    g = c & (h >= 35) & (h < 58)
    out[g] = "gold"
    out[g & (s > 0.7) & (v > 0.85)] = "yellow"
    out[g & (v < 0.45)] = "brown"
    y = c & (h >= 58) & (h < 75)
    out[y] = "olive"
    out[y & (v > 0.75) & (s > 0.5)] = "yellow"
    out[c & (h >= 75) & (h < 165)] = "green"
    out[c & (h >= 165) & (h < 200)] = "teal"
    b = c & (h >= 200) & (h < 255)
    out[b] = "blue"
    out[b & (v < 0.4)] = "navy"
    pu = c & (h >= 255) & (h < 290)
    out[pu] = "purple"
    out[pu & (s < 0.4)] = "lavender"
    pk = c & (h >= 290) & (h < 345)
    out[pk] = "pink"
    out[pk & (s >= 0.72) & (v < 0.9)] = "magenta"
    out[v < 0.16] = "black"
    return out


def colour_names(img: Image.Image, max_colours: int = 2, min_share: float = 0.15) -> list[str]:
    """Main colours of the product in plain words, from pixels only (instant).
    The background is guessed from the photo's border and ignored."""
    small = img.convert("RGB").copy()
    small.thumbnail((96, 96))
    a = np.asarray(small).astype(np.float64) / 255
    px = a.reshape(-1, 3)
    border = np.concatenate([a[:3].reshape(-1, 3), a[-3:].reshape(-1, 3),
                             a[:, :3].reshape(-1, 3), a[:, -3:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    keep = np.abs(px - bg).sum(axis=1) > 0.18
    if keep.sum() < len(px) * 0.05:  # product fills the frame / no clear background
        keep[:] = True
    p = px[keep]
    mx, mn = p.max(axis=1), p.min(axis=1)
    d = np.where(mx - mn == 0, 1e-9, mx - mn)
    r, g, b = p[:, 0], p[:, 1], p[:, 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx == 0, 0, (mx - mn) / np.where(mx == 0, 1, mx))
    names = _name_hsv(h, s, mx)
    words, counts = np.unique(names, return_counts=True)
    share = dict(zip(words, counts / counts.sum()))
    if "maroon" in share and "red" in share:  # shades of one red
        share["red"] += share.pop("maroon")
    ranked = sorted(share, key=share.get, reverse=True)
    picked = [w for w in ranked if share[w] >= min_share][:max_colours]
    return picked or ranked[:1]


def join_colours(colours: list[str]) -> str:
    cs = [c for c in dict.fromkeys(c.strip().lower() for c in colours) if c]
    if len(cs) <= 1:
        return cs[0] if cs else ""
    return ", ".join(cs[:-1]) + " and " + cs[-1]


def singular(word: str) -> str:
    """'Dresses' -> 'dress', 'Earrings' -> 'earrings' (pairs stay plural)."""
    w = word.strip()
    low = w.lower()
    if not low or low.endswith(("earrings", "pants", "jeans", "shorts", "leggings", "sets")):
        return low
    for suffix, rep in (("ches", "ch"), ("shes", "sh"), ("sses", "ss"), ("ies", "y")):
        if low.endswith(suffix):
            return low[: -len(suffix)] + rep
    if low.endswith("s") and not low.endswith("ss"):
        return low[:-1]
    return low


_OPTIONAL = re.compile(r"\[([^\[\]]*)\]")
_PH = re.compile(r"\{(\w+)\}")


def fill(template: str, values: dict[str, str]) -> str:
    def opt(m: re.Match) -> str:
        part = m.group(1)
        names = _PH.findall(part)
        return part if names and all(values.get(n, "").strip() for n in names) else ""

    out = _OPTIONAL.sub(opt, template)
    out = _PH.sub(lambda m: values.get(m.group(1), "").strip(), out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([.,:;!])", r"\1", out)
    out = re.sub(r"([.,:;])(?:\s*[.,:;])+", r"\1", out)
    out = out.strip(" ,;:-")
    # capitalise each sentence
    return re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)


@dataclass
class ShopStyle:
    """What the template step needs to know about the shop."""
    name: str = ""
    kind: str = "other"
    name_template: str = ""
    desc_template: str = ""
    mode: str = "fast"

    def templates(self) -> tuple[str, str]:
        dn, dd = DEFAULT_TEMPLATES.get(self.kind, DEFAULT_TEMPLATES["other"])
        return (self.name_template.strip() or dn, self.desc_template.strip() or dd)


@dataclass
class Known:
    """Facts the seller already gave us; these always win over the AI."""
    type: str = ""
    material: str = ""
    size: str = ""
    brand: str = ""
    extra_tags: list[str] = field(default_factory=list)


def draft_from(style: ShopStyle, facts: Facts, known: Known, fallback_type: str = "item") -> Draft:
    type_ = known.type.strip() or facts.type or fallback_type
    colour = join_colours(facts.colours)
    values = {
        "type": type_, "colour": colour, "pattern": facts.pattern,
        "material": known.material or facts.material, "size": known.size or facts.size,
        "brand": known.brand, "text": facts.text, "shop": style.name or "our shop",
    }
    name_t, desc_t = style.templates()
    name = fill(name_t, values) or fill("{colour} {type}", values) or type_.capitalize()
    tags = [t for t in dict.fromkeys(
        [*(c for c in facts.colours), *type_.split(), *facts.pattern.split()[:3], *known.extra_tags]
    ) if len(t) > 2][:8]
    return Draft(
        name=name[:80],
        category=known.type or facts.type,
        description=fill(desc_t, values)[:500],
        color=colour,
        material=values["material"],
        size=values["size"],
        brand=known.brand,
        price_cents=facts.price_cents,
        tags=tags,
    )


def instant_facts(img: Image.Image) -> Facts:
    return Facts(colours=colour_names(img))


def describe_item(ai_vision, style: ShopStyle, images: list[Image.Image], known: Known,
                  seller: str = "", hint: str = "", fallback_type: str = "item") -> tuple[Draft, str]:
    """Returns (draft, mode actually used). Fast mode falls back to instant when
    the model isn't running, so the seller always gets a starting point."""
    from .vision import VisionUnavailable

    mode = style.mode if style.mode in MODES else "fast"
    if mode == "full":
        return ai_vision.describe(images, hint=hint, seller=seller), "full"
    if mode == "fast":
        try:
            facts = ai_vision.facts(images, hint=hint, seller=seller)
            if not facts.colours:
                facts.colours = colour_names(images[0])
            return draft_from(style, facts, known, fallback_type), "fast"
        except VisionUnavailable:
            pass
    return draft_from(style, instant_facts(images[0]), known, fallback_type), "instant"


def preview(style: ShopStyle) -> Draft:
    """Sample output for the settings screen."""
    sample = {
        "clothing": (Facts(type="dress", colours=["red", "pink"], pattern="floral embroidery"), Known(size="M")),
        "jewellery": (Facts(type="earrings", colours=["gold"], pattern="pearl drops"), Known(material="Gold-tone")),
        "soap": (Facts(type="soap", colours=["lavender"], text="Lavender Dream", pattern="dried petals"), Known(size="4 oz")),
        "candle": (Facts(type="candle", colours=["cream"], text="Vanilla Bean"), Known(size="8 oz")),
    }.get(style.kind, (Facts(type="keychain", colours=["blue", "white"], pattern="wave print"), Known()))
    return draft_from(style, *sample)
