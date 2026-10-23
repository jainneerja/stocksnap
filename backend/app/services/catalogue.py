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


def _footer(d: ImageDraw.ImageDraw, shop: str, page: int, total: int) -> None:
    f = _font(22)
    d.line((MARGIN, PAGE_H - 80, PAGE_W - MARGIN, PAGE_H - 80), fill=(220, 210, 198), width=2)
    d.text((MARGIN, PAGE_H - 62), shop, font=f, fill=MUTED)
    t = f"{page} / {total}"
    d.text((PAGE_W - MARGIN - d.textlength(t, font=f), PAGE_H - 62), t, font=f, fill=MUTED)


def _cover(shop: str, title: str, subtitle: str, count: int, logo: Optional[Image.Image],
           first: Optional[Image.Image], owner: str = "") -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), (252, 249, 244))
    d = ImageDraw.Draw(page)
    y = 170
    if logo is not None:
        lg = ImageOps.contain(logo.convert("RGBA"), (260, 260))
        page.paste(lg, ((PAGE_W - lg.width) // 2, y), lg)
        y += lg.height + 50
    lines = [(shop, 64, True, INK, 30 if not owner else 6)]
    if owner:
        lines.append((owner, 32, False, MUTED, 30))
    lines.append((title, 46, False, ACCENT, 24))
    for text, size, bold, colour, gap in lines:
        f = _font(size, bold)
        for line in _wrap(d, text, f, PAGE_W - 2 * MARGIN, 2):
            d.text(((PAGE_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=colour)
            y += size + 14
        y += gap
    if subtitle:
        f = _font(30)
        for line in _wrap(d, subtitle, f, PAGE_W - 2 * MARGIN, 3):
            d.text(((PAGE_W - d.textlength(line, font=f)) / 2, y), line, font=f, fill=MUTED)
            y += 44
    if first is not None:
        size = min(PAGE_W - 2 * MARGIN - 200, PAGE_H - y - 330)
        if size > 300:
            ph = _fit(first, size, size, (252, 249, 244))
            page.paste(ph, ((PAGE_W - size) // 2, y + 60))
    f = _font(28)
    meta = f"{count} product{'s' if count != 1 else ''} · {time.strftime('%d %B %Y')}"
    d.text(((PAGE_W - d.textlength(meta, font=f)) / 2, PAGE_H - 200), meta, font=f, fill=MUTED)
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


def _design_pages(cat: dict, items: list[dict], photo, shop: str) -> list[Image.Image]:
    """One block per design: heading (design, size, colours, price), then the colour photos."""
    cols = 3 if cat.get("columns") == 3 else 2
    gap = 24
    cw = (PAGE_W - 2 * MARGIN - (cols - 1) * gap) // cols
    ph = cw
    cap = 50
    top, bottom = MARGIN + 70, PAGE_H - 110
    product = (cat.get("product") or "").strip()
    pages: list[Image.Image] = []
    page = d = None
    y = 0

    def new_page():
        nonlocal page, d, y
        page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        d = ImageDraw.Draw(page)
        d.text((MARGIN, MARGIN), cat.get("title") or shop, font=_font(30, True), fill=INK)
        pages.append(page)
        y = top

    new_page()
    fh, fs, fc, fp = _font(36, True), _font(24), _font(24, True), _font(30, True)
    for key, group in _groups(items):
        head_h = 118
        # cell height follows the photos' shape: wide photos get shorter cells
        ratios = sorted(photo(it).height / max(photo(it).width, 1) for it in group)
        ph = int(cw * min(max(ratios[len(ratios) // 2], 0.55), 1.25))
        rows_n = -(-len(group) // cols)
        whole = head_h + rows_n * (ph + cap + 10)
        if y + whole > bottom and y > top and whole <= bottom - top:
            new_page()   # keep a design on one page when it fits on one
        if y + head_h + ph + cap > bottom and y > top:
            new_page()
        first = group[0]
        title = " – ".join(x for x in (product, first.get("design") or first.get("name") or key) if x)
        if first.get("size"):
            title += f" · Size {first['size']}"
        d.rectangle((MARGIN, y, PAGE_W - MARGIN, y + head_h - 18), fill=CARD_BG)
        d.text((MARGIN + 20, y + 14), title, font=fh, fill=INK)
        colours = [it.get("colour") or it.get("name") for it in group]
        info = f"{len(group)} colour{'s' if len(group) != 1 else ''}: " + ", ".join(c for c in colours if c)
        d.text((MARGIN + 20, y + 62), info, font=fs, fill=MUTED)
        prices = list(dict.fromkeys(it.get("price", "").strip() for it in group if it.get("price", "").strip()))
        if prices:
            pt = " / ".join(prices[:3])
            d.text((PAGE_W - MARGIN - 20 - d.textlength(pt, font=fp), y + 30), pt, font=fp, fill=ACCENT)
        y += head_h
        for k, it in enumerate(group):
            c = k % cols
            if c == 0 and k:
                y += ph + cap + 10
            if c == 0 and y + ph + cap > bottom:
                new_page()
            x = MARGIN + c * (cw + gap)
            page.paste(_fit(photo(it), cw, ph), (x, y))
            d.rectangle((x, y, x + cw - 1, y + ph - 1), outline=(228, 219, 206), width=2)
            label = colours[k] or ""
            code = (it.get("code") or "").strip()
            d.text((x + 4, y + ph + 10), label, font=fc, fill=INK)
            if code:
                d.text((x + cw - 4 - d.textlength(code, font=fs), y + ph + 10), code, font=fs, fill=MUTED)
        y += ph + cap + 34
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
    top, bottom = MARGIN + 70, PAGE_H - 110
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
            page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
            d = ImageDraw.Draw(page)
            d.text((MARGIN, MARGIN), cat.get("title") or shop, font=fh, fill=INK)
            for k, it in enumerate(chunk):
                r, c = divmod(k, cols)
                page.paste(_card(it, photo(it), cw, ch), (MARGIN + c * (cw + gap), top + r * (ch + gap)))
            body.append(page)
    pages = [cover, *body]
    if n_designs:
        # the cover counts designs, not photos
        cd = ImageDraw.Draw(cover)
        f = _font(28)
        cd.rectangle((0, PAGE_H - 210, PAGE_W, PAGE_H - 160), fill=(252, 249, 244))
        meta = f"{n_designs} design{'s' if n_designs != 1 else ''} · {len(items)} colours · {time.strftime('%d %B %Y')}"
        cd.text(((PAGE_W - cd.textlength(meta, font=f)) / 2, PAGE_H - 200), meta, font=f, fill=MUTED)
    for i, pg in enumerate(pages, start=1):
        _footer(ImageDraw.Draw(pg), shop, i, len(pages))
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
