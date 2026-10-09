"""Product presets for bulk intake.

A preset says how to photograph a product type, which questions to ask once
per batch (answers apply to every piece), how to count (every piece unique, or
identical goods grouped and counted) and what the AI should look for.

Questions with `field` set fill that inventory field; others are stored as
item attributes. An answer starting with "Mixed" or "Not sure" leaves the
field to the AI / the seller.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

Mode = Literal["unique", "identical"]


@dataclass
class Question:
    key: str
    label: str
    kind: Literal["select", "text", "money"] = "text"
    options: list[str] = field(default_factory=list)
    field: Optional[str] = None  # category | material | size | cost | price | None (= attribute)
    help: str = ""


@dataclass
class Preset:
    key: str
    label: str
    mode: Mode
    background: str
    tips: list[str]
    questions: list[Question]
    ai_hint: str
    per_photo: str  # how many pieces fit one photo
    categories: list[str] = field(default_factory=list)  # fixed list keeps inventory tidy

    def to_dict(self) -> dict:
        return asdict(self)


JEWELLERY_CATEGORIES = ["Earrings", "Rings", "Necklaces", "Bracelets", "Pendants", "Pins & Brooches",
                        "Anklets", "Hair accessories", "Sets", "Other jewellery"]
SOAP_CATEGORIES = ["Bar soap", "Liquid soap", "Bath bombs", "Body butter", "Gift sets", "Other bath"]
CLOTHING_CATEGORIES = ["T-shirts", "Tops & blouses", "Shirts", "Hoodies & sweatshirts", "Sweaters",
                       "Dresses", "Skirts", "Pants & jeans", "Shorts", "Jackets & coats", "Kids & baby",
                       "Scarves & accessories", "Other clothing"]
CANDLE_CATEGORIES = ["Jar candles", "Tin candles", "Pillar candles", "Wax melts", "Other candles"]

# Words a model (or a person) might use -> the category they belong to.
SYNONYMS = {
    "earring": "Earrings", "stud": "Earrings", "hoop": "Earrings", "huggie": "Earrings", "drop": "Earrings",
    "ring": "Rings", "band": "Rings",
    "necklace": "Necklaces", "chain": "Necklaces", "choker": "Necklaces", "lariat": "Necklaces",
    "bracelet": "Bracelets", "bangle": "Bracelets", "cuff": "Bracelets",
    "pendant": "Pendants", "charm": "Pendants", "locket": "Pendants",
    "pin": "Pins & Brooches", "brooch": "Pins & Brooches",
    "anklet": "Anklets",
    "hair": "Hair accessories", "clip": "Hair accessories", "barrette": "Hair accessories", "headband": "Hair accessories", "scrunchie": "Hair accessories",
    "set": "Sets",
    "bar soap": "Bar soap", "soap bar": "Bar soap", "liquid": "Liquid soap", "hand wash": "Liquid soap",
    "bath bomb": "Bath bombs", "butter": "Body butter", "gift": "Gift sets",
    "t-shirt": "T-shirts", "tshirt": "T-shirts", "tee": "T-shirts", "short sleeve": "T-shirts",
    "long sleeve": "Tops & blouses", "blouse": "Tops & blouses", "top": "Tops & blouses",
    "tank": "Tops & blouses", "camisole": "Tops & blouses",
    "shirt": "Shirts", "button-down": "Shirts", "flannel": "Shirts",
    "hoodie": "Hoodies & sweatshirts", "sweatshirt": "Hoodies & sweatshirts", "crewneck": "Hoodies & sweatshirts",
    "sweater": "Sweaters", "cardigan": "Sweaters", "jumper": "Sweaters", "pullover": "Sweaters",
    "dress": "Dresses", "skirt": "Skirts",
    "jean": "Pants & jeans", "pant": "Pants & jeans", "trouser": "Pants & jeans", "legging": "Pants & jeans",
    "jogger": "Pants & jeans", "shorts": "Shorts",
    "jacket": "Jackets & coats", "coat": "Jackets & coats", "blazer": "Jackets & coats", "vest": "Jackets & coats",
    "onesie": "Kids & baby", "baby": "Kids & baby", "kid": "Kids & baby", "toddler": "Kids & baby",
    "scarf": "Scarves & accessories", "hat": "Scarves & accessories", "beanie": "Scarves & accessories",
    "tote": "Scarves & accessories", "bag": "Scarves & accessories", "sock": "Scarves & accessories",
    "jar": "Jar candles", "tin": "Tin candles", "pillar": "Pillar candles", "melt": "Wax melts",
}


def normalize_category(raw: str, allowed: list[str]) -> str:
    """Map whatever the AI said onto the preset's fixed list. Free text when no list."""
    raw = (raw or "").strip()
    if not allowed:
        return raw
    if not raw:
        return allowed[-1]
    low = raw.lower()
    for c in allowed:
        if c.lower() == low or c.lower().rstrip("s") == low.rstrip("s"):
            return c
    # Longest synonym first ("bar soap" beats "bar", "sweatshirt" beats "shirt"),
    # matched at a word start so "headband" isn't a "band" (ring) and "printed" isn't a "tin".
    for word in sorted(SYNONYMS, key=len, reverse=True):
        if SYNONYMS[word] in allowed and re.search(r"(?<![a-z])" + re.escape(word), low):
            return SYNONYMS[word]
    return allowed[-1]


COMMON_TIPS = [
    "Daylight or two lamps from the sides. No flash - it causes glare.",
    "Hold the phone straight above the tray, parallel to it, and fill the frame.",
    "Leave about a finger-width gap between items. Touching items are counted as one.",
]

# Free-text note passed to the AI only (not stored on items). Lets the seller say
# what the pieces really are when the model can't tell from the photo alone.
_about = Question(
    "about", "What are these? (tells the AI)", field="ai_note",
    help="Optional. Use your own words, e.g. \"doll outfits\", \"pet bandanas\", \"dresses for small statues\".",
)

_cost = Question("cost", "Cost per piece ($)", "money", field="cost", help="What you paid. Used for profit.")
_price = Question("price", "Selling price per piece ($)", "money", field="price", help="You can change it per item later.")

PRESETS: dict[str, Preset] = {
    p.key: p
    for p in [
        Preset(
            key="clothing",
            label="Clothing",
            mode="identical",
            background="Plain sheet or card that contrasts with the clothes: white for dark clothes, dark grey or black for light ones.",
            tips=COMMON_TIPS + [
                "Fold each piece neatly and lay it flat, front facing up. Don't let pieces overlap.",
                "One size per batch: answer the Size question below so every piece gets counted in the right size.",
                "Same design, same size = counted together. Different designs become separate items.",
            ],
            per_photo="4-8 folded pieces",
            categories=CLOTHING_CATEGORIES,
            questions=[
                _about,
                Question("type", "What's in this batch?", "select", ["Mixed"] + CLOTHING_CATEGORIES[:-1],
                         field="category"),
                Question("size", "Size (if all the same)", field="size", help="e.g. M, XL, 2T. Do one size per batch."),
                Question("material", "Fabric (optional)", field="material", help="e.g. 100% organic cotton"),
                Question("brand", "Brand (optional)", field="brand", help="Leave blank for your own label."),
                _cost,
                _price,
            ],
            ai_hint=(
                "The photo shows ONE clothing item laid flat. Say what type it is, its colour, the print "
                "or graphic, neckline and sleeves, and fabric if obvious. Copy any printed text or size "
                "label exactly. Don't guess the size."
            ),
        ),
        Preset(
            key="jewellery",
            label="Jewellery",
            mode="unique",
            background="Matte black: velvet, felt or black foam board. Use plain white card only for black pieces (onyx, gunmetal).",
            tips=COMMON_TIPS + [
                "Earring pairs: let the two earrings touch so the pair counts as one item.",
                "Lay chains straight or in a loose loop, never tangled. Necklaces on their own tray, about 6 per photo.",
                "Put one metal type per batch so the answers below apply to every piece.",
            ],
            per_photo="20-30 small pieces (studs, rings, charms) or about 6 necklaces",
            categories=JEWELLERY_CATEGORIES,
            questions=[
                _about,
                Question("type", "What's on this tray?", "select",
                         ["Mixed"] + JEWELLERY_CATEGORIES[:-1],
                         field="category"),
                Question("metal", "Metal", "select",
                         ["Gold-tone", "Silver-tone", "Rose gold-tone", "Sterling silver (925)", "Gold-plated",
                          "Solid gold", "Stainless steel", "Brass / copper", "Mixed / not sure"],
                         field="material", help="The AI can see colour but can't verify metal - you know best."),
                Question("stones", "Stones", "select",
                         ["None", "Cubic zirconia", "Crystal / glass", "Faux pearls", "Real pearls",
                          "Natural gemstones", "Mixed / not sure"]),
                Question("nickel_free", "Nickel-free?", "select", ["Not sure", "Yes", "No"]),
                Question("supplier", "Supplier (optional)"),
                _cost,
                _price,
            ],
            ai_hint=(
                "The photo shows ONE piece of jewellery (or a pair of earrings). Say what type it is "
                "(stud, hoop, drop earrings, ring, pendant, chain, bracelet...), its colour and finish, "
                "shape, motif and style, and any visible stones by colour. Never claim metal purity "
                "or that stones are real gemstones."
            ),
        ),
        Preset(
            key="soap",
            label="Soaps & bath",
            mode="identical",
            background="Plain matte surface that contrasts with the packaging: white card for dark or kraft wrappers, black for white boxes.",
            tips=COMMON_TIPS + [
                "Labels facing up and readable - the AI reads the name, scent and weight from them.",
                "Lay out every bar you want counted. For full cartons, photograph one and type the count.",
            ],
            per_photo="15-25 bars or boxes",
            categories=SOAP_CATEGORIES,
            questions=[
                _about,
                Question("type", "What's in this batch?", "select",
                         ["Mixed"] + SOAP_CATEGORIES[:-1],
                         field="category"),
                Question("weight", "Weight / size, if all the same", help="e.g. 4 oz. Leave blank to read it from labels.",
                         field="size"),
                Question("maker", "Maker / brand (optional)", field="brand",
                         help="Leave blank if it's your own; the AI reads brands off labels."),
                _cost,
                _price,
            ],
            ai_hint=(
                "The photo shows ONE packaged soap or bath product. Read the printed label carefully "
                "and copy the product name, brand, scent and net weight exactly as printed. Use the "
                "printed product name (with scent) as the name and the net weight as the size."
            ),
        ),
        Preset(
            key="candle",
            label="Candles",
            mode="identical",
            background="Plain matte surface that contrasts with the jars: white for dark/amber jars, black for white or clear ones.",
            tips=COMMON_TIPS + ["Labels facing the camera; shoot from slightly above if the label is on the side."],
            per_photo="10-20 candles",
            categories=CANDLE_CATEGORIES,
            questions=[
                _about,
                Question("wax", "Wax", "select",
                         ["Soy", "Coconut", "Beeswax", "Paraffin", "Blend", "Not sure"], field="material"),
                Question("size", "Size, if all the same", help="e.g. 8 oz", field="size"),
                _cost,
                _price,
            ],
            ai_hint=(
                "The photo shows ONE candle. Read any label exactly: product name, scent, size. "
                "Describe the vessel (jar, tin, pillar), colour and style."
            ),
        ),
        Preset(
            key="other",
            label="Something else",
            mode="identical",
            background="Plain matte surface that contrasts with your items: black for light or shiny items, white for dark ones.",
            tips=COMMON_TIPS,
            per_photo="10-30 items, depending on size",
            questions=[
                _about,
                Question("type", "Category", field="category", help="e.g. Keychains, Stickers"),
                Question("material", "Material (optional)", field="material"),
                Question("brand", "Brand / maker (optional)", field="brand"),
                _cost,
                _price,
            ],
            ai_hint="The photo shows ONE product. Read any printed label exactly and describe the item.",
        ),
    ]
}

UNSURE_PREFIXES = ("mixed", "not sure", "none")


def resolve_answers(preset: Preset, answers: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Split answers into item field values and display attributes."""
    fields: dict = {}
    attrs: dict[str, str] = {}
    for q in preset.questions:
        raw = str(answers.get(q.key, "") or "").strip()
        if not raw:
            continue
        if q.kind == "money":
            try:
                fields[f"{q.field}_cents"] = max(0, round(float(raw.replace("$", "")) * 100))
            except ValueError:
                pass
            continue
        if q.field == "ai_note":
            continue  # for the AI prompt only, see ai_note()
        unsure = raw.lower().startswith(UNSURE_PREFIXES)
        if q.field and not unsure:
            fields[q.field] = raw
        elif not q.field and raw.lower() not in ("not sure", "mixed / not sure"):
            attrs[q.label.replace(" (optional)", "").rstrip("?")] = raw
    return fields, attrs


def ai_note(answers: dict[str, str]) -> str:
    return str(answers.get("about", "") or "").strip()[:300]
