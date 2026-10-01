"""Synthetic tray photos for testing piece detection."""

import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GOLD = (212, 175, 55)
SILVER = (192, 192, 200)
ROSE = (215, 150, 140)


def _noise_bg(size, base, amount=10, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.clip(np.array(base, np.float32) + rng.normal(0, amount, (size[1], size[0], 1)), 0, 255)
    return Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))


def jewellery_tray(cols=6, rows=4, seed=1, touching_pair_at=None, size=(2400, 1800)):
    """Returns (jpeg bytes, number of separate items)."""
    random.seed(seed)
    img = _noise_bg(size, (18, 18, 20), seed=seed)
    d = ImageDraw.Draw(img)
    cw, ch = size[0] / cols, size[1] / rows
    count = 0
    for r in range(rows):
        for c in range(cols):
            cx, cy = (c + 0.5) * cw, (r + 0.5) * ch
            colour = random.choice([GOLD, SILVER, ROSE])
            kind = (r * cols + c) % 5
            s = min(cw, ch) * random.uniform(0.18, 0.28)
            if (r, c) == touching_pair_at:
                d.ellipse((cx - 2 * s, cy - s, cx, cy + s), fill=colour)
                d.ellipse((cx - 2, cy - s, cx + 2 * s - 2, cy + s), fill=colour)  # touching twin
            elif kind == 0:  # hoop: thin ring with a hole
                d.ellipse((cx - s, cy - s, cx + s, cy + s), outline=colour, width=max(6, int(s * 0.12)))
            elif kind == 1:  # stud with a stone
                d.ellipse((cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5), fill=colour)
                d.ellipse((cx - s * 0.25, cy - s * 0.25, cx + s * 0.25, cy + s * 0.25), fill=(30, 160, 90))
            elif kind == 2:  # pendant on a short chain
                d.line((cx, cy - s * 1.3, cx, cy), fill=colour, width=5)
                d.polygon([(cx, cy), (cx - s * 0.5, cy + s * 0.8), (cx + s * 0.5, cy + s * 0.8)], fill=colour)
            elif kind == 3:  # ring
                d.ellipse((cx - s * 0.7, cy - s * 0.7, cx + s * 0.7, cy + s * 0.7), outline=colour, width=int(s * 0.2))
            else:  # bar brooch
                d.rounded_rectangle((cx - s, cy - s * 0.3, cx + s, cy + s * 0.3), radius=8, fill=colour)
            count += 1
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue(), count


SOAPS = [
    ("LAVENDER", (150, 120, 200)),
    ("OATMEAL", (205, 180, 140)),
    ("CHARCOAL", (60, 60, 60)),
]


def soap_tray(layout, size=(2400, 1800), seed=2):
    """layout: list of soap indexes in reading order (4 per row). Returns jpeg bytes."""
    img = _noise_bg(size, (238, 236, 230), amount=4, seed=seed)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    cols = 4
    rows = (len(layout) + cols - 1) // cols
    cw, ch = size[0] / cols, size[1] / max(rows, 1)
    for i, idx in enumerate(layout):
        r, c = divmod(i, cols)
        cx, cy = (c + 0.5) * cw, (r + 0.5) * ch
        name, colour = SOAPS[idx]
        bw, bh = cw * 0.62, ch * 0.5
        # soft shadow
        d.rounded_rectangle((cx - bw / 2 + 12, cy - bh / 2 + 12, cx + bw / 2 + 12, cy + bh / 2 + 12), 14, fill=(205, 203, 198))
        d.rounded_rectangle((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), 14, fill=colour)
        d.rectangle((cx - bw * 0.4, cy - bh * 0.22, cx + bw * 0.4, cy + bh * 0.22), fill=(250, 250, 245))
        d.text((cx, cy), name, font=font, fill=(40, 40, 40), anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
