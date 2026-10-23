"""Product catalogue: a folder of product photos -> a PDF catalogue.

The seller drops plain product photos (one photo per product) into a folder and
picks it in the app. Each photo gets a name and short description (the shop's
own description settings: instant / fast AI / detailed AI), the seller adds
prices, and the app lays everything out as a printable / WhatsApp-able PDF:
a cover page, then a grid of product cards.

Pure Pillow: no extra PDF library needed.
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageOps

from .imagelab import _font

# A4 at 150 dpi
PAGE_W, PAGE_H = 1240, 1754
MARGIN = 70
INK = (40, 33, 28)
MUTED = (120, 108, 96)
ACCENT = (150, 45, 60)
CARD_BG = (250, 247, 242)
PHOTO_BG = (243, 238, 230)

CAMERA_NAME = re.compile(r"^(img|dsc|dscn|pxl|photo|image|whatsapp image|whatsapp|wa|screenshot|mvimg|p)[\s_-]*\d", re.I)


def name_from_file(filename: str) -> str:
    """'red_leaves-dress.jpg' -> 'Red leaves dress'; camera names ('IMG_2041') -> ''."""
    stem = Path(filename).stem
    if CAMERA_NAME.match(stem) or re.fullmatch(r"[\d_\-\s()]+", stem):
        return ""
    words = re.sub(r"[_\-.]+", " ", stem)
    words = re.sub(r"\s*\(\d+\)$", "", words).strip()  # "dress (2)" -> "dress"
    return (words[:1].upper() + words[1:])[:80]


SIZE_DIR = re.compile(r"^(?:size|sz)[\s_-]*([0-9]+(?:\s*[-–to]+\s*[0-9]+)?|[a-z]{1,4})$", re.I)
DESIGN_DIR = re.compile(r"^(?:design|style|model|d)[\s_-]*(\w+)$", re.I)


def parse_path(rel_path: str) -> dict:
    """Folders say what the photo is: '.../Size 7/Design 2/Light Pink.jpg' ->
    {size: '7', design: 'Design 2', colour: 'Light pink'}. Unknown folders are ignored."""
    parts = [p for p in re.split(r"[\\/]", rel_path or "") if p]
    out = {"size": "", "design": "", "colour": ""}
    for part in parts[:-1]:
        name = part.strip()
        m = SIZE_DIR.match(name)
        if m:
            out["size"] = m.group(1).replace(" ", "")
            continue
        m = DESIGN_DIR.match(name)
        if m:
            out["design"] = f"Design {m.group(1)}"
    if out["size"] or out["design"]:
        out["colour"] = name_from_file(parts[-1] if parts else "")
    return out


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= width:
            cur = test
            continue
        if cur:
            lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _fit(img: Image.Image, w: int, h: int, bg=PHOTO_BG) -> Image.Image:
    """Whole photo inside w x h (no cropping), on a soft background."""
    img = img.convert("RGB")
    canvas = Image.new("RGB", (w, h), bg)
    im = ImageOps.contain(img, (w, h), Image.LANCZOS)
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return canvas


# ---- festive look: cream paper, maroon and gold, serif headings
CREAM = (253, 248, 238)
MAROON = (112, 22, 38)
MAROON_DARK = (78, 12, 26)
GOLD = (191, 145, 58)
GOLD_LIGHT = (232, 205, 140)


def _serif(size: int, bold: bool = True, italic: bool = False):
    names = (["DejaVuSerif-BoldItalic.ttf", "georgiaz.ttf", "Georgia Bold Italic.ttf"] if bold and italic else
             ["DejaVuSerif-Italic.ttf", "georgiai.ttf", "Georgia Italic.ttf"] if italic else
             ["DejaVuSerif-Bold.ttf", "georgiab.ttf", "Georgia Bold.ttf", "timesbd.ttf"] if bold else
             ["DejaVuSerif.ttf", "georgia.ttf", "Georgia.ttf", "times.ttf"])
    from PIL import ImageFont

    for n in names:
        for p in (n, f"/usr/share/fonts/truetype/dejavu/{n}", f"C:/Windows/Fonts/{n}", f"/Library/Fonts/{n}"):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return _font(size, bold)


def _centre(d, y, text, font, fill):
    d.text(((PAGE_W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _ornament(d, cx: int, y: int, half: int = 160, colour=GOLD) -> None:
    """—— ◆ —— divider."""
    d.line((cx - half, y, cx - 18, y), fill=colour, width=3)
    d.line((cx + 18, y, cx + half, y), fill=colour, width=3)
    d.polygon([(cx, y - 10), (cx + 10, y), (cx, y + 10), (cx - 10, y)], fill=colour)
    for k in (-1, 1):
        x = cx + k * (half + 10)
        d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=colour)


def _frame(d) -> None:
    """Thin double gold border round the page, with small corner diamonds."""
    for inset, w in ((28, 4), (40, 2)):
        d.rectangle((inset, inset, PAGE_W - inset, PAGE_H - inset), outline=GOLD, width=w)
    for x, y in ((34, 34), (PAGE_W - 34, 34), (34, PAGE_H - 34), (PAGE_W - 34, PAGE_H - 34)):
        d.polygon([(x, y - 12), (x + 12, y), (x, y + 12), (x - 12, y)], fill=GOLD)


def _shadowed(page: Image.Image, img: Image.Image, x: int, y: int, radius: int = 18, border=GOLD) -> None:
    """Photo with rounded corners, a soft shadow and a thin gold edge."""
    from PIL import ImageFilter

    w, h = img.size
    sh = Image.new("L", (w + 60, h + 60), 0)
    ImageDraw.Draw(sh).rounded_rectangle((30, 36, 30 + w, 36 + h), radius, fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(12))
    page.paste((90, 60, 40), (x - 30, y - 30), sh)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    page.paste(img, (x, y), mask)
    ImageDraw.Draw(page).rounded_rectangle((x, y, x + w - 1, y + h - 1), radius, outline=border, width=3)


def _footer(d: ImageDraw.ImageDraw, shop: str, page: int, total: int, contact: str = "") -> None:
    f = _serif(22, bold=False, italic=True)
    y = PAGE_H - 92
    left = shop + (f"  ·  {contact}" if contact else "")
    d.text((70, y), left, font=f, fill=MAROON)
    t = f"{page} / {total}"
    d.text((PAGE_W - 70 - d.textlength(t, font=f), y), t, font=f, fill=MAROON)


def _cover(shop: str, title: str, subtitle: str, count: int, logo: Optional[Image.Image],
           first: Optional[Image.Image], owner: str = "") -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
    d = ImageDraw.Draw(page)
    # maroon band at the top with the shop name in gold
    band = 330 if not logo else 400
    d.rectangle((0, 0, PAGE_W, band), fill=MAROON)
    d.rectangle((0, band, PAGE_W, band + 8), fill=GOLD)
    y = 70
    if logo is not None:
        lg = ImageOps.contain(logo.convert("RGBA"), (130, 130))
        page.paste(lg, ((PAGE_W - lg.width) // 2, y - 20), lg)
        y += 120
    f = _serif(80)
    for line in _wrap(d, shop, f, PAGE_W - 200, 2):
        _centre(d, y, line, f, GOLD_LIGHT)
        y += 92
    if owner:
        _centre(d, y + 6, owner, _serif(32, bold=False, italic=True), (240, 220, 200))
    _ornament(d, PAGE_W // 2, band - 46, 200, GOLD_LIGHT)
    # product title
    y = band + 70
    ft = _serif(66)
    for line in _wrap(d, title, ft, PAGE_W - 200, 2):
        _centre(d, y, line, ft, MAROON)
        y += 78
    if subtitle:
        fs = _serif(30, bold=False, italic=True)
        for line in _wrap(d, subtitle, fs, PAGE_W - 240, 2):
            _centre(d, y + 6, line, fs, MAROON_DARK)
            y += 42
    _ornament(d, PAGE_W // 2, y + 34)
    # the front photo, framed
    if first is not None:
        top = y + 90
        box_w, box_h = PAGE_W - 300, PAGE_H - top - 160
        im = ImageOps.contain(first.convert("RGB"), (box_w, box_h), Image.LANCZOS)
        _shadowed(page, im, (PAGE_W - im.width) // 2, top + (box_h - im.height) // 2)
    _frame(d)
    return page


def _card(item: dict, photo: Image.Image, w: int, h: int) -> Image.Image:
    card = Image.new("RGB", (w, h), CARD_BG)
    d = ImageDraw.Draw(card)
    pad = 22
    text_h = (200 if w > 450 else 190) if item.get("description") else 130
    ph_h = h - text_h - pad
    card.paste(_fit(photo, w - 2 * pad, ph_h - pad), (pad, pad))
    y = ph_h + 12
    fname = _font(32 if w > 450 else 27, True)
    for line in _wrap(d, item.get("name") or "", fname, w - 2 * pad, 2):
        d.text((pad, y), line, font=fname, fill=INK)
        y += fname.size + 6
    price, code = (item.get("price") or "").strip(), (item.get("code") or "").strip()
    fp, fc = _font(30 if w > 450 else 26, True), _font(22)
    if price:
        d.text((pad, y + 4), price, font=fp, fill=ACCENT)
    if code:
        d.text((w - pad - d.textlength(code, font=fc), y + 10), code, font=fc, fill=MUTED)
    y += fp.size + 14
    if item.get("description"):
        fd = _font(22 if w > 450 else 20)
        for line in _wrap(d, item["description"], fd, w - 2 * pad, 3):
            if y + fd.size > h - 8:
                break
            d.text((pad, y), line, font=fd, fill=MUTED)
            y += fd.size + 6
    d.rectangle((0, 0, w - 1, h - 1), outline=(228, 219, 206), width=2)
    return card


def _groups(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """Products by design (and size), in folder order."""
    order: list[str] = []
    by: dict[str, list[dict]] = {}
    for it in items:
        key = " · ".join(x for x in (it.get("design") or "", f"Size {it['size']}" if it.get("size") else "") if x) \
            or it.get("name") or "Products"
        if key not in by:
            order.append(key)
            by[key] = []
        by[key].append(it)
    return [(k, by[k]) for k in order]


NAMED = {"red": (200, 30, 40), "maroon": (120, 20, 40), "pink": (230, 80, 150), "dark pink": (200, 30, 110),
         "light pink": (245, 170, 200), "rani pink": (215, 30, 120), "magenta": (200, 30, 160),
         "orange": (245, 120, 30), "yellow": (245, 205, 40), "mustard": (210, 165, 40), "gold": (205, 160, 60),
         "golden": (205, 160, 60), "green": (40, 160, 80), "dark green": (20, 100, 50), "light green": (140, 210, 120),
         "parrot green": (110, 200, 40), "mehendi": (120, 130, 40), "blue": (40, 80, 200), "dark blue": (20, 40, 120),
         "navy": (20, 30, 90), "light blue": (130, 180, 235), "sky blue": (120, 190, 240), "royal blue": (40, 60, 190),
         "purple": (120, 50, 170), "violet": (130, 60, 190), "lavender": (180, 160, 220), "peach": (250, 180, 140),
         "cream": (245, 235, 205), "white": (250, 250, 250), "silver": (200, 200, 205), "black": (25, 25, 25),
         "brown": (120, 75, 40), "wine": (110, 20, 50), "teal": (20, 130, 130), "turquoise": (40, 190, 190),
         "firozi": (40, 190, 190), "rust": (180, 80, 40), "beige": (220, 200, 165)}


def _swatch(img: Image.Image, label: str = "") -> tuple:
    """Dot colour: the colour named in the label ("Dark Pink"), else read from the photo."""
    low = label.lower().replace("(on idol)", "").strip()
    for name in sorted(NAMED, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return NAMED[name]
    sm = img.convert("RGB").resize((60, 60))
    px = [p for p in sm.crop((12, 12, 48, 48)).getdata()]
    strong = [p for p in px if max(p) - min(p) > 50] or px
    strong.sort(key=lambda p: sum(p))
    return strong[len(strong) // 2]


def _design_pages(cat: dict, items: list[dict], photo, shop: str) -> list[Image.Image]:
    """One block per design: heading (design, size, price), then every colour as a framed card."""
    cols = 3 if cat.get("columns") == 3 else 2
    gap = 30
    side = 90
    cw = (PAGE_W - 2 * side - (cols - 1) * gap) // cols
    cap = 66
    top, bottom = 190, PAGE_H - 120
    product = (cat.get("product") or "").strip()
    pages: list[Image.Image] = []
    page = d = None
    y = 0

    def new_page():
        nonlocal page, d, y
        page = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
        d = ImageDraw.Draw(page)
        d.rectangle((0, 0, PAGE_W, 120), fill=MAROON)
        d.rectangle((0, 120, PAGE_W, 126), fill=GOLD)
        f = _serif(40)
        _centre(d, 38, cat.get("title") or shop, f, GOLD_LIGHT)
        pages.append(page)
        y = top

    new_page()
    fh, fsize, fc, fcode, fp = _serif(42), _font(24, True), _serif(25), _font(20), _font(30, True)
    for key, group in _groups(items):
        head_h = 100
        ratios = sorted(photo(it).height / max(photo(it).width, 1) for it in group)
        ph = int(cw * min(max(ratios[len(ratios) // 2], 0.55), 1.2))
        rows_n = -(-len(group) // cols)
        whole = head_h + rows_n * (ph + cap + 24)
        if y + whole > bottom and y > top and whole <= bottom - top:
            new_page()   # keep a design on one page when it fits on one
        if y + head_h + ph + cap > bottom and y > top:
            new_page()
        first = group[0]
        name = first.get("design") or first.get("name") or key
        # heading: "Design 1" in maroon serif, a size pill, the price on a gold tag
        d.text((side, y), name, font=fh, fill=MAROON)
        x = side + d.textlength(name, font=fh) + 22
        if first.get("size"):
            t = f"Size {first['size']}"
            tw = d.textlength(t, font=fsize)
            d.rounded_rectangle((x, y + 8, x + tw + 32, y + 48), 20, outline=MAROON, width=2)
            d.text((x + 16, y + 14), t, font=fsize, fill=MAROON)
        prices = list(dict.fromkeys(it.get("price", "").strip() for it in group if it.get("price", "").strip()))
        if prices:
            pt = " / ".join(prices[:3])
            tw = d.textlength(pt, font=fp)
            x1 = PAGE_W - side
            d.rounded_rectangle((x1 - tw - 44, y, x1, y + 54), 27, fill=GOLD)
            d.text((x1 - tw - 22, y + 9), pt, font=fp, fill=(255, 255, 255))
        if product:
            d.text((side, y + 54), f"{product} · {len(group)} colour{'s' if len(group) != 1 else ''}",
                   font=_serif(22, bold=False, italic=True), fill=MUTED)
        y += head_h
        for k, it in enumerate(group):
            c = k % cols
            if c == 0 and k:
                y += ph + cap + 24
            if c == 0 and y + ph + cap > bottom:
                new_page()
            x = side + c * (cw + gap)
            # white card: photo + colour name with a colour dot
            d.rounded_rectangle((x - 8, y - 8, x + cw + 8, y + ph + cap), 20, fill=(255, 255, 255),
                                outline=GOLD_LIGHT, width=2)
            img = photo(it)
            _shadowed(page, _fit(img, cw - 16, ph - 16, (250, 246, 238)), x, y, 14, GOLD_LIGHT)
            label = (it.get("colour") or it.get("name") or "").strip()
            ly = y + ph + 12
            dot = _swatch(img, label)
            d.ellipse((x + 4, ly + 6, x + 26, ly + 28), fill=dot, outline=(200, 190, 175))
            d.text((x + 36, ly + 2), label, font=fc, fill=INK)
            code = (it.get("code") or "").strip()
            if code:
                d.text((x + cw - d.textlength(code, font=fcode), ly + 7), code, font=fcode, fill=MUTED)
        y += ph + cap + 56
    return pages


def build_pdf(cat: dict, photo_dir: Path, shop: str, logo_path: Optional[Path] = None,
              show_prices: bool = True) -> bytes:
    """cat: {title, subtitle, columns, layout, cover, owner, items:[{photo, name, price, code, ...}]}
    show_prices=False gives the same catalogue without any price (e.g. for resellers)."""
    items = [it for it in cat["items"] if it.get("include", True) and it.get("status") != "failed"]
    if not show_prices:
        items = [{**it, "price": ""} for it in items]
    shop = cat.get("shop") or shop
    cols = 3 if cat.get("columns") == 3 else 2
    rows = 3 if cols == 3 else 2
    per_page = cols * rows
    gap = 26
    top, bottom = 170, PAGE_H - 120
    cw = (PAGE_W - 2 * MARGIN - (cols - 1) * gap) // cols
    ch = (bottom - top - (rows - 1) * gap) // rows

    def photo(it):
        return Image.open(photo_dir / it["photo"]).convert("RGB")

    logo = None
    if logo_path and logo_path.is_file():
        try:
            logo = Image.open(logo_path)
        except OSError:
            logo = None
    designs = cat.get("layout") == "designs"
    cover_img = None
    if cat.get("cover") and (photo_dir / cat["cover"]).is_file():
        cover_img = Image.open(photo_dir / cat["cover"]).convert("RGB")
    elif items:
        cover_img = photo(items[0])
    cover = _cover(shop, cat.get("title") or "Catalogue", cat.get("subtitle") or "", len(items), logo,
                   cover_img, cat.get("owner", ""))
    if designs:
        n_designs = len(_groups(items))
        body = _design_pages(cat, items, photo, shop)
    else:
        n_designs = 0
        body = []
        chunks = [items[i:i + per_page] for i in range(0, len(items), per_page)] or [[]]
        fh = _font(30, True)
        for chunk in chunks:
            page = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
            d = ImageDraw.Draw(page)
            d.rectangle((0, 0, PAGE_W, 120), fill=MAROON)
            d.rectangle((0, 120, PAGE_W, 126), fill=GOLD)
            _centre(d, 38, cat.get("title") or shop, _serif(40), GOLD_LIGHT)
            for k, it in enumerate(chunk):
                r, c = divmod(k, cols)
                page.paste(_card(it, photo(it), cw, ch), (MARGIN + c * (cw + gap), top + r * (ch + gap)))
            body.append(page)
    pages = [cover, *body]
    for i, pg in enumerate(pages, start=1):
        if i > 1:
            _footer(ImageDraw.Draw(pg), shop, i, len(pages), cat.get("contact", ""))
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buf.getvalue()


# ---------------------------------------------------------------- catalogues from a folder on this PC

COVER_NAMES = {"front_page", "front", "main_image", "main", "cover", "cover_page", "first_page"}
PRICE_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]+)?)|[-–]\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*$", re.I)
CATALOGUE_PREFIX = re.compile(r"^\s*catal\w*\s*\d*\s*[-–:.]?\s*", re.I)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def split_owner(folder_name: str) -> tuple[str, str]:
    """'Ekaa Creations (Anjana Aggarwal)' -> ('Ekaa Creations', 'Anjana Aggarwal')."""
    m = re.match(r"^\s*(.*?)\s*\(([^()]*)\)\s*$", folder_name)
    return (m.group(1), m.group(2).strip()) if m else (folder_name.strip(), "")


def product_name(folder_name: str) -> str:
    """'Catalogue 1 -  Ladoo Gopal' -> 'Ladoo Gopal'."""
    name = CATALOGUE_PREFIX.sub("", folder_name).strip(" -–")
    return re.sub(r"\s+", " ", name) or folder_name.strip()


def design_and_price(folder_name: str) -> tuple[str, str]:
    """'Design 1 - Rs 70' -> ('Design 1', '₹70'); 'Design 2' -> ('Design 2', '')."""
    m = PRICE_RE.search(folder_name)
    price = ""
    name = folder_name
    if m:
        price = "₹" + (m.group(1) or m.group(2)).replace(",", "")
        name = folder_name[:m.start()]
    name = re.sub(r"\s+", " ", name).strip(" -–:")
    d = DESIGN_DIR.match(name)
    return (f"Design {d.group(1)}" if d else name), price


def _is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith((".", "_"))


def _colour_label(filename: str, product: str) -> tuple[str, bool]:
    """Colour from the file name; product words are dropped ('Ladoo Gopal Blue' -> 'Blue').
    Returns (label, on_idol) - on_idol when the product's name was in the file name."""
    label = name_from_file(filename)
    words = {w.lower() for w in re.findall(r"\w+", product)} | {"laddu", "ladoo", "gopal", "idol"}
    kept = [w for w in label.split() if w.lower() not in words]
    on_idol = len(kept) < len(label.split())
    label = " ".join(kept)
    return (label[:1].upper() + label[1:]) if label else "", on_idol


def scan_product(folder: Path) -> dict:
    """One product folder -> {product, folder, cover, items}. Items come from
    [Size X/]Design Y - Rs P/<Colour>.jpg (sizes optional)."""
    product = product_name(folder.name)
    cover = next((p for p in sorted(folder.iterdir()) if _is_image(p) and p.stem.lower() in COVER_NAMES), None)
    items = []

    def walk(d: Path, size: str):
        for sub in sorted((x for x in d.iterdir() if x.is_dir() and not x.name.startswith((".", "_"))),
                          key=lambda x: _natural_key(x.name)):
            m = SIZE_DIR.match(sub.name.strip())
            if m:
                walk(sub, m.group(1).replace(" ", ""))
                continue
            design, price = design_and_price(sub.name)
            photos = sorted((p for p in sub.iterdir() if _is_image(p)), key=lambda p: _natural_key(p.name))
            for p in photos:
                colour, on_idol = _colour_label(p.name, product)
                items.append({"path": p, "size": size, "design": design, "price": price,
                              "colour": (f"{colour} (on idol)" if on_idol and colour else colour)})
            walk(sub, size)  # deeper folders (rare)

    walk(folder, "")
    # loose photos (no design folder) are products of their own
    for p in sorted((p for p in folder.iterdir() if _is_image(p) and p != cover), key=lambda p: _natural_key(p.name)):
        colour, _ = _colour_label(p.name, product)
        items.append({"path": p, "size": "", "design": "", "price": "", "colour": colour})
    return {"product": product, "folder": folder, "cover": cover, "items": items}


def scan_shop(root: Path) -> dict:
    """Shop folder -> {shop, owner, catalogues: [...]}; a product folder works too."""
    def looks_like_product(d: Path) -> bool:
        return any(_is_image(p) and p.stem.lower() in COVER_NAMES for p in d.iterdir()) or any(
            x.is_dir() and (SIZE_DIR.match(x.name.strip()) or DESIGN_DIR.match(design_and_price(x.name)[0]))
            for x in d.iterdir())

    if looks_like_product(root):
        shop, owner = split_owner(root.parent.name)
        products = [root]
    else:
        shop, owner = split_owner(root.name)
        products = sorted((x for x in root.iterdir() if x.is_dir() and not x.name.startswith((".", "_"))),
                          key=lambda x: _natural_key(x.name))
    cats = [c for c in (scan_product(p) for p in products) if c["items"]]
    return {"shop": shop, "owner": owner, "catalogues": cats}


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def cover_line(items: list[dict]) -> str:
    """'Sizes 4 to 5 · 8 colours · 2 designs'"""
    sizes = list(dict.fromkeys(it["size"] for it in items if it.get("size")))
    designs = {(it.get("size"), it.get("design")) for it in items if it.get("design")}
    parts = []
    if sizes:
        nums = [s for s in sizes if s.isdigit()]
        if len(sizes) == 1:
            parts.append(f"Size {sizes[0]}")
        elif len(nums) == len(sizes):
            parts.append(f"Sizes {min(map(int, nums))} to {max(map(int, nums))}")
        else:
            parts.append("Sizes " + ", ".join(sizes))
    colours = {it.get("colour", "").replace(" (on idol)", "") for it in items if it.get("colour")}
    if colours:
        parts.append(f"{len(colours)} colour{'s' if len(colours) != 1 else ''}")
    if designs:
        parts.append(f"{len(designs)} design{'s' if len(designs) != 1 else ''}")
    return " · ".join(parts)
