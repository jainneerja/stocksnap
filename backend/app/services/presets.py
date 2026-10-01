"""Product presets for bulk intake.

A preset says how to photograph a product type, which questions to ask once
per batch (answers apply to every piece), how to count (every piece unique, or
identical goods grouped and counted) and what the AI should look for.

Questions with `field` set fill that inventory field; others are stored as
item attributes. An answer starting with "Mixed" or "Not sure" leaves the
field to the AI / the seller.
"""

from __future__ import annotations

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

    def to_dict(self) -> dict:
        return asdict(self)


COMMON_TIPS = [
    "Daylight or two lamps from the sides. No flash - it causes glare.",
    "Hold the phone straight above the tray, parallel to it, and fill the frame.",
    "Leave about a finger-width gap between items. Touching items are counted as one.",
]

_cost = Question("cost", "Cost per piece ($)", "money", field="cost", help="What you paid. Used for profit.")
_price = Question("price", "Selling price per piece ($)", "money", field="price", help="You can change it per item later.")

PRESETS: dict[str, Preset] = {
    p.key: p
    for p in [
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
            questions=[
                Question("type", "What's on this tray?", "select",
                         ["Mixed", "Earrings", "Rings", "Necklaces", "Bracelets", "Pendants", "Anklets", "Brooches"],
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
            questions=[
                Question("type", "What's in this batch?", "select",
                         ["Mixed", "Bar soap", "Liquid soap", "Bath bombs", "Body butter", "Gift sets"],
                         field="category"),
                Question("weight", "Weight / size, if all the same", help="e.g. 4 oz. Leave blank to read it from labels.",
                         field="size"),
                Question("maker", "Maker / brand (optional)"),
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
            questions=[
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
                Question("type", "Category", field="category", help="e.g. Keychains, Stickers"),
                Question("material", "Material (optional)", field="material"),
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
        unsure = raw.lower().startswith(UNSURE_PREFIXES)
        if q.field and not unsure:
            fields[q.field] = raw
        elif not q.field and raw.lower() not in ("not sure", "mixed / not sure"):
            attrs[q.label.replace(" (optional)", "").rstrip("?")] = raw
    return fields, attrs
