"""Find and count separate items laid out on a plain background.

Classic computer vision (OpenCV, Apache-2.0): fast on any laptop CPU, no model
download, and very reliable when the photo follows the setup guide - a plain,
matte, contrasting background with a small gap between items.

  1. Estimate the background colour from the photo's border.
  2. Mark pixels that differ from it (in Lab colour space, so a gold piece on
     black velvet and a kraft-paper soap on white card both stand out).
  3. Clean up: remove specks, close small gaps inside a piece (thin hoops,
     chain links), fill holes.
  4. Each remaining blob is one item. Blobs that are mostly mat edge, shadow
     or dust are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

WORK_PX = 1600  # analyse at this size; boxes are scaled back to the original


@dataclass
class Piece:
    x: int
    y: int
    w: int
    h: int

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


@dataclass
class Segmentation:
    pieces: list[Piece]
    background: str  # "dark" | "light"
    warning: str = ""


def find_pieces(img: Image.Image, _depth: int = 0) -> Segmentation:
    rgb = np.asarray(img.convert("RGB"))
    H, W = rgb.shape[:2]
    scale = min(1.0, WORK_PX / max(H, W))
    small = cv2.resize(rgb, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    h, w = small.shape[:2]

    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_RGB2LAB).astype(np.float32)
    border = max(4, int(0.03 * min(h, w)))
    ring = np.concatenate([
        lab[:border].reshape(-1, 3), lab[-border:].reshape(-1, 3),
        lab[:, :border].reshape(-1, 3), lab[:, -border:].reshape(-1, 3),
    ])
    bg = np.median(ring, axis=0)
    dark_bg = bg[0] < 128

    # Light backgrounds: soft shadows mostly change lightness, so weight it less.
    l_weight = 1.0 if dark_bg else 0.45
    diff = np.sqrt(l_weight * (lab[..., 0] - bg[0]) ** 2 + (lab[..., 1] - bg[1]) ** 2 + (lab[..., 2] - bg[2]) ** 2)
    diff8 = np.clip(diff * 2, 0, 255).astype(np.uint8)
    # Threshold from the background's own noise (fabric texture, sensor grain), not
    # from the items: a low-contrast kraft wrapper next to bright ones must still count.
    border_diff = np.concatenate([
        diff8[:border].ravel(), diff8[-border:].ravel(), diff8[:, :border].ravel(), diff8[:, -border:].ravel(),
    ])
    thresh = float(np.clip(np.percentile(border_diff, 99) * 1.6, 24, 90))
    mask = (diff8 >= thresh).astype(np.uint8) * 255

    k = max(3, int(round(min(h, w) * 0.004)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    kc = max(5, int(round(min(h, w) * 0.012)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc)))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_img = h * w
    min_area = area_img * 0.0004
    boxes = []
    dropped_edge = 0
    mat = None  # a big blob in the middle = the mat/tray, with the table showing around it
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        if area > area_img * 0.35 and (mat is None or area > mat[4]):
            mat = (x, y, bw, bh, area)
        touches = (x <= 1) + (y <= 1) + (x + bw >= w - 1) + (y + bh >= h - 1)
        if touches >= 2 or area > area_img * 0.35:
            dropped_edge += 1  # table edge, mat border or a hand
            continue
        boxes.append((x, y, bw, bh))

    if mat is not None and _depth == 0 and len(boxes) <= 1:
        # Re-run inside the mat, so its colour becomes the background.
        x, y, bw, bh, _ = mat
        inset = int(0.02 * min(bw, bh))
        box = (int((x + inset) / scale), int((y + inset) / scale),
               int((x + bw - inset) / scale), int((y + bh - inset) / scale))
        inner = find_pieces(img.crop(box), _depth=1)
        for p in inner.pieces:
            p.x += box[0]
            p.y += box[1]
        if inner.pieces:
            inner.warning = ""
        return inner

    boxes = _reading_order(boxes)
    pieces = []
    for x, y, bw, bh in boxes:
        pad = int(0.08 * max(bw, bh)) + 2
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        pieces.append(Piece(int(x0 / scale), int(y0 / scale), int((x1 - x0) / scale), int((y1 - y0) / scale)))

    warning = ""
    if dropped_edge:
        warning = "Part of the photo edge looked like the table or mat border - keep everything on the mat and fill the frame."
    if not pieces:
        warning = "No items found. Use a plain background that contrasts with your items and keep the phone straight above."
    return Segmentation(pieces=pieces, background="dark" if dark_bg else "light", warning=warning)


def _reading_order(boxes: list[tuple[int, int, int, int]]):
    """Number items row by row, left to right, like reading a page."""
    if not boxes:
        return boxes
    med_h = float(np.median([b[3] for b in boxes]))
    rows: list[list] = []
    for b in sorted(boxes, key=lambda b: b[1] + b[3] / 2):
        cy = b[1] + b[3] / 2
        if rows and abs(cy - rows[-1][0]) < med_h * 0.6:
            rows[-1][1].append(b)
            rows[-1][0] = np.mean([bb[1] + bb[3] / 2 for bb in rows[-1][1]])
        else:
            rows.append([cy, [b]])
    return [b for _, row in rows for b in sorted(row, key=lambda b: b[0])]


def crop(img: Image.Image, p: Piece) -> Image.Image:
    return img.crop((p.x, p.y, p.x + p.w, p.y + p.h))
