"""Scene templates: put a REAL product photo into a ready-made scene.

A seller uploads one nice base image (their own photo, or one made once with
any AI tool) and marks two things on it:

  * the product area - an oval where the product lies (e.g. the skirt), and
  * optionally a top-piece box (e.g. the chest, for a dress with a bodice).

Everything else is worked out automatically: the old product inside those
areas is recognised by its colours and removed, and whatever is not old
product (an idol's hands, a necklace, hair) is kept on top of the new one.
A brush fixes anything the automatic step gets wrong.

Rendering a product is pure image processing - no generative AI - so it takes
about a second on any laptop and the product's colours and details stay
exactly as photographed.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 1600  # scenes are stored at most this big

# Where the top piece sits on a flat-laid round dress photo (fractions of the
# product's bounding box): the bodice flap above the centre. Works for the
# common Laddu Gopal style; other shapes can turn the top piece off.
DEFAULT_TOP_SRC = [0.331, 0.267, 0.729, 0.580]
DEFAULT_TOP_OUTLINE = [[0.335, 0.268], [0.733, 0.268], [0.733, 0.50], [0.71, 0.55], [0.66, 0.575],
                       [0.42, 0.578], [0.37, 0.555], [0.337, 0.50]]


@dataclass
class Stroke:
    points: list[list[float]]  # [[x, y], ...] as fractions of the scene
    r: float = 0.02  # brush radius, fraction of the scene width


@dataclass
class SceneTemplate:
    id: str
    name: str
    width: int = 0
    height: int = 0
    created: float = 0.0
    # product area: an oval, fractions of the scene
    cx: float = 0.5
    top: float = 0.40
    bottom: float = 0.92
    rx: float = 0.46
    tilt: float = 0.33  # 0.5 = seen from straight above, smaller = more perspective
    # optional top piece box (x0, y0, x1, y1), fractions of the scene
    top_box: Optional[list[float]] = None
    top_src: list[float] = field(default_factory=lambda: list(DEFAULT_TOP_SRC))
    top_outline: list[list[float]] = field(default_factory=lambda: [list(p) for p in DEFAULT_TOP_OUTLINE])
    keep: list[Stroke] = field(default_factory=list)  # always show the scene here (on top)
    remove: list[Stroke] = field(default_factory=list)  # always treat as old product
    # exact outlines (polygons, fractions of the scene): precise for arms and hands
    keep_outlines: list[list[list[float]]] = field(default_factory=list)
    remove_outlines: list[list[list[float]]] = field(default_factory=list)
    shading: float = 0.5
    shadow: float = 0.38
    scale: float = 1.0  # new product size relative to the oval (the oval also marks what gets cleared)
    sensitivity: float = 0.025  # colour share (in the oval's outer ring) that counts as old product

    @classmethod
    def from_dict(cls, d: dict) -> "SceneTemplate":
        d = dict(d)
        d["keep"] = [Stroke(**s) for s in d.get("keep", [])]
        d["remove"] = [Stroke(**s) for s in d.get("remove", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- geometry


def skirt_quad(t: SceneTemplate) -> np.ndarray:
    """Where the corners of the product photo's square go, so the round product
    lies in the oval in perspective (far side narrower), its centre at the
    'waist' point a `tilt` fraction down the oval."""
    w, h = t.width, t.height
    cx, yb, yf = t.cx * w, t.top * h, t.bottom * h
    tilt = min(max(t.tilt, 0.15), 0.5)
    rx = t.rx * w
    # smaller product: shrink around the waist point (centre of the round product)
    k = min(max(t.scale, 0.5), 1.2)
    yw = yb + tilt * (yf - yb)
    yb, yf, rx = yw - (yw - yb) * k, yw + (yf - yw) * k, rx * k
    wb = rx / (2 - 2 * tilt)
    wf = wb * (1 - tilt) / tilt
    return np.float32([[cx - wb, yb], [cx + wb, yb], [cx + wf, yf], [cx - wf, yf]])


def area_mask(t: SceneTemplate) -> np.ndarray:
    """The oval plus the top-piece box, in scene pixels."""
    w, h = t.width, t.height
    m = np.zeros((h, w), np.uint8)
    cy, ry = (t.top + t.bottom) / 2 * h, (t.bottom - t.top) / 2 * h
    cv2.ellipse(m, (int(t.cx * w), int(cy)), (int(t.rx * w), int(ry)), 0, 0, 360, 255, -1)
    if t.top_box:
        x0, y0, x1, y1 = t.top_box
        cv2.rectangle(m, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), 255, -1)
    return m


def _strokes(t: SceneTemplate, strokes: list[Stroke]) -> np.ndarray:
    m = np.zeros((t.height, t.width), np.uint8)
    for s in strokes:
        if isinstance(s, dict):
            s = Stroke(**s)
        pts = np.int32([[x * t.width, y * t.height] for x, y in s.points])
        r = max(2, int(s.r * t.width))
        if len(pts) == 1:
            cv2.circle(m, tuple(int(v) for v in pts[0]), r, 255, -1)
        else:
            cv2.polylines(m, [pts], False, 255, r * 2, lineType=cv2.LINE_AA)
            for p in (pts[0], pts[-1]):
                cv2.circle(m, tuple(int(v) for v in p), r, 255, -1)
    return m


def _tidy_keep(m: np.ndarray, lab: np.ndarray, prod_centres: np.ndarray) -> np.ndarray:
    sel = m > 0
    if sel.sum() < 30 or not len(prod_centres):
        return m
    px = lab[sel]
    own = np.median(px, axis=0)
    d = np.linalg.norm(px[:, None, :] - prod_centres[None], axis=2)
    nearest = d.argmin(axis=1)
    alien = np.linalg.norm(prod_centres - own, axis=1) > 35  # product colours unlike this shape
    far = np.linalg.norm(px - own, axis=1) > 45  # and the pixel itself looks nothing like the shape
    drop = (d.min(axis=1) < 20) & alien[nearest] & far
    piece = np.zeros_like(m)
    piece[sel] = np.where(drop, 0, 255)
    piece = cv2.morphologyEx(piece, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # biggest parts only, holes filled (a red dot on a ball stays)
    n, cl, stats, _ = cv2.connectedComponentsWithStats(piece)
    if n > 1:
        big = stats[1:, cv2.CC_STAT_AREA].max()
        piece = np.isin(cl, [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 0.15 * big]).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(piece, cnts, -1, 255, -1)
    return cv2.bitwise_and(piece, m)


def _outlines(t: SceneTemplate, polys: list[list[list[float]]]) -> np.ndarray:
    m = np.zeros((t.height, t.width), np.uint8)
    for poly in polys:
        if len(poly) >= 3:
            cv2.fillPoly(m, [np.int32([[x * t.width, y * t.height] for x, y in poly])], 255, lineType=cv2.LINE_AA)
    return m


# ---------------------------------------------------------------- analysis


def analyse(scene: np.ndarray, t: SceneTemplate) -> tuple[np.ndarray, np.ndarray]:
    """Returns (old_product, keep_on_top) masks.

    1. Learn the old product's look from the outer ring of the oval, where
       only product lies: its main
       colours.
    2. Inside the marked areas, a pixel is old product when it is close to
       one of those colours. Parts in the same colours as the product (gold
       arms next to gold sequins) need a stroke of the "keep" brush.
    3. Whatever isn't old product (hands, jewellery, hair) stays on top.
    4. The old product also gets removed where it spills outside the oval.
    5. The seller's brush strokes override everything."""
    h, w = scene.shape[:2]
    region = area_mask(t)
    sel = region > 0
    lab = cv2.cvtColor(scene, cv2.COLOR_BGR2LAB).astype(np.float32)

    # outer ring of the oval: only product there
    yy, xx = np.mgrid[0:h, 0:w]
    cy, ry = (t.top + t.bottom) / 2 * h, max((t.bottom - t.top) / 2 * h, 1)
    rr = np.sqrt(((xx - t.cx * w) / max(t.rx * w, 1)) ** 2 + ((yy - cy) / ry) ** 2)
    ring = (rr > 0.62) & (rr < 0.97) & (yy > cy - 0.3 * ry)

    ref = lab[ring]
    rng = np.random.default_rng(0)
    sample = ref[rng.choice(len(ref), size=min(len(ref), 40000), replace=False)]
    k = 10
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(0)  # same scene + same marks = same result every time
    _, _, centres = cv2.kmeans(sample, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)

    ring_lbl = np.linalg.norm(ref[:, None, :] - centres[None], axis=2).argmin(axis=1)
    share = np.bincount(ring_lbl, minlength=k) / max(len(ring_lbl), 1)
    prod_centres = centres[share >= t.sensitivity]
    main_centres = centres[share >= 0.12]  # the product's main fabric colours

    # product = close to one of the product's colours (Lab distance)
    grow = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.2 * w) | 1,) * 2))
    gsel = grow > 0
    dist = np.linalg.norm(lab[gsel][:, None, :] - prod_centres[None], axis=2).min(axis=1)
    prod_px = dist < 22
    product = np.zeros((h, w), np.uint8)
    product[gsel] = np.where(prod_px, 255, 0)
    product = cv2.morphologyEx(product, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    # background (table, wall): learnt from outside the grown area; inside the
    # oval it is simply covered by the new product, never kept on top
    outside = (grow == 0)
    if t.top_box:
        outside[: int(t.top_box[3] * h), max(int((t.top_box[0] - 0.06) * w), 0): int((t.top_box[2] + 0.06) * w)] = False
    bg_px = lab[outside]
    background = np.zeros((h, w), np.uint8)
    if len(bg_px) > 500:
        bs = bg_px[rng.choice(len(bg_px), size=min(len(bg_px), 20000), replace=False)]
        _, blbl, bcent = cv2.kmeans(bs, 4, None, crit, 2, cv2.KMEANS_PP_CENTERS)
        bshare = np.bincount(blbl.ravel(), minlength=4) / len(blbl)
        bcent = bcent[bshare > 0.1]
        dist = np.linalg.norm(lab[gsel][:, None, :] - bcent[None], axis=2).min(axis=1)
        background[gsel] = np.where(dist < 14, 255, 0)

    # keep-on-top: solid non-product, non-background shapes inside the marked areas
    keep = cv2.bitwise_and(region, cv2.bitwise_not(cv2.bitwise_or(product, background)))
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, cl, stats, _ = cv2.connectedComponentsWithStats(keep)
    small = np.zeros(n, bool)
    small[1:] = stats[1:, cv2.CC_STAT_AREA] < 0.004 * sel.sum()
    keep[small[cl]] = 0
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    filled = keep.copy()  # fill holes inside kept shapes (e.g. a hand's shadowed palm)
    cnts, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, cnts, -1, 255, -1)
    keep = cv2.bitwise_and(filled, region)

    # old product: the marked areas (minus kept parts) plus product-coloured
    # spill-over connected to them outside the oval
    # (never into anything that looks like the table or wall - matters when the
    # product is cream or beige like the background)
    spill = cv2.bitwise_and(product, cv2.bitwise_not(cv2.bitwise_or(region, background)))
    # never grow up into whatever stands on the product (the idol / model):
    # the column above the top piece (or the middle of the oval), down to the oval's centre
    if t.top_box:
        cx0, cx1 = t.top_box[0] - 0.06, t.top_box[2] + 0.06
    else:
        cx0, cx1 = t.cx - 0.3 * t.rx, t.cx + 0.3 * t.rx
    spill[: int(cy), max(int(cx0 * w), 0): int(cx1 * w)] = 0
    spill[: int(t.top * h) - int(0.02 * h), :] = 0
    n, cl, _, _ = cv2.connectedComponentsWithStats(spill)
    touching = np.unique(cl[(cv2.dilate(region, np.ones((5, 5), np.uint8)) > 0) & (spill > 0)])
    spill = np.isin(cl, touching[touching > 0]).astype(np.uint8) * 255
    old = cv2.bitwise_or(cv2.bitwise_and(region, cv2.bitwise_not(keep)), spill)
    old = cv2.morphologyEx(old, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    # head guard: whatever stands directly above the top piece (an idol's face
    # and neck, a model's head) is never old product, even if the oval overlaps it
    if t.top_box:
        bx0, by0, bx1, _ = t.top_box
        guard = np.zeros((h, w), np.uint8)
        guard[: int(by0 * h), max(int((bx0 - 0.03) * w), 0): int((bx1 + 0.03) * w)] = 255
        guard = cv2.bitwise_and(guard, cv2.dilate(region, np.ones((15, 15), np.uint8)))
        old = cv2.bitwise_and(old, cv2.bitwise_not(guard))
        keep = cv2.bitwise_or(keep, guard)  # stays on top: the new dress's back edge goes behind it

    # the seller's corrections win (brush strokes and outlines). Inside each kept
    # shape, pixels in one of the old product's main colours that is clearly
    # different from the shape's own colour (pink fabric round a gold arm) are
    # dropped, so a slightly loose outline still gives a clean edge.
    r_strokes = _strokes(t, t.remove) | _outlines(t, t.remove_outlines)
    shapes = [_strokes(t, [s]) for s in t.keep] + [_outlines(t, [p]) for p in t.keep_outlines]
    k_strokes = np.zeros((h, w), np.uint8)
    for m in shapes:
        k_strokes |= _tidy_keep(m, lab, main_centres)
    keep = cv2.bitwise_and(cv2.bitwise_or(keep, k_strokes), cv2.bitwise_not(r_strokes))
    old = cv2.bitwise_and(cv2.bitwise_or(old, r_strokes), cv2.bitwise_not(keep))
    return old, keep


def empty_plate(scene: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """The scene with the old product removed (background filled in smoothly)."""
    small = cv2.resize(scene, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    hs = cv2.resize(hole, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    hs = cv2.dilate(hs, np.ones((5, 5), np.uint8))
    filled = cv2.GaussianBlur(cv2.inpaint(small, hs, 9, cv2.INPAINT_TELEA), (9, 9), 0)
    big = cv2.resize(filled, (scene.shape[1], scene.shape[0]), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    big += np.random.default_rng(0).normal(0, 1.6, scene.shape).astype(np.float32)
    a = _soft(cv2.dilate(hole, np.ones((9, 9), np.uint8)), 6)
    return _over(scene.astype(np.float32), np.clip(big, 0, 255), a)


# ---------------------------------------------------------------- render


def _soft(mask: np.ndarray, px: int) -> np.ndarray:
    k = px * 2 + 1
    return cv2.GaussianBlur(mask, (k, k), 0).astype(np.float32) / 255 if px > 0 else mask.astype(np.float32) / 255


def _over(base: np.ndarray, top: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    a = alpha[..., None]
    return top.astype(np.float32) * a + base.astype(np.float32) * (1 - a)


def _bbox(alpha: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(alpha > 128)
    if not len(xs):
        h, w = alpha.shape
        return 0, 0, w - 1, h - 1
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _poly(shape, pts) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [np.int32(pts)], 255)
    return m


def render(t: SceneTemplate, scene: np.ndarray, plate: np.ndarray, keep: np.ndarray,
           product: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """product: BGR photo of the product; alpha: its cut-out mask (0-255)."""
    h, w = scene.shape[:2]
    # solid product (fill any holes the cut-out left), then trim the fringe
    cnts, _ = cv2.findContours((alpha > 128).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solid = np.zeros_like(alpha)
    cv2.drawContours(solid, cnts, -1, 255, -1)
    alpha = np.maximum(alpha, cv2.erode(solid, np.ones((9, 9), np.uint8)))
    alpha = cv2.erode(alpha, np.ones((5, 5), np.uint8))  # no background fringe
    x0, y0, x1, y1 = _bbox(alpha)
    bw, bh = max(x1 - x0, 1), max(y1 - y0, 1)

    src_sq = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    H = cv2.getPerspectiveTransform(src_sq, skirt_quad(t))
    flat = product
    top_mask_src = None
    if t.top_box:
        outline = [[x0 + u * bw, y0 + v * bh] for u, v in t.top_outline]
        top_mask_src = cv2.bitwise_and(_poly(product.shape, outline), alpha)
        # On the floor, the top piece covered part of the skirt in the photo. Fill
        # that patch with the same dress's embroidery from the side (rotated 90
        # degrees: same distance from the centre, so the same ring of pattern),
        # so the top piece doesn't appear twice. The opposite side (180) can be a
        # plain seam that looks like the top piece carrying on below the waist.
        hide = cv2.dilate(_poly(product.shape, outline), np.ones((25, 25), np.uint8))
        R = cv2.getRotationMatrix2D(((x0 + x1) / 2, (y0 + y1) / 2), 90, 1.0)
        flipped = cv2.warpAffine(product, R, (product.shape[1], product.shape[0]))
        flat = _over(product.astype(np.float32), flipped, _soft(hide, 6)).astype(np.uint8)

    skirt = cv2.warpPerspective(flat, H, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    a_skirt = cv2.warpPerspective(alpha, H, (w, h))

    # soft shadow on the floor
    sm = np.roll(a_skirt, (int(0.012 * h), 0), axis=(0, 1))
    k = int(0.035 * w) | 1
    sm = cv2.GaussianBlur(sm, (k, k), 0).astype(np.float32) / 255 * t.shadow
    canvas = plate * (1 - sm[..., None])

    # big, soft light and folds from the scene (heavily blurred: no pattern carries over)
    lum = cv2.cvtColor(scene, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    lum_f = cv2.GaussianBlur(lum, (0, 0), 0.025 * w)
    region = area_mask(t) > 0
    ref = float(np.median(lum_f[region])) if region.any() else 128.0
    gain = np.clip(1 + t.shading * (lum_f / max(ref, 1) - 1), 0.7, 1.2)[..., None]

    canvas = _over(canvas, np.clip(skirt * gain, 0, 255), _soft(a_skirt, 1))

    if t.top_box and top_mask_src is not None:
        sx0, sy0, sx1, sy1 = (x0 + t.top_src[0] * bw, y0 + t.top_src[1] * bh,
                              x0 + t.top_src[2] * bw, y0 + t.top_src[3] * bh)
        bx0, by0, bx1, by1 = (t.top_box[0] * w, t.top_box[1] * h, t.top_box[2] * w, t.top_box[3] * h)
        # slightly narrower at the waist, like a body
        inset = 0.07 * (bx1 - bx0)
        dst = np.float32([[bx0, by0], [bx1, by0], [bx1 - inset, by1], [bx0 + inset, by1]])
        Ht = cv2.getPerspectiveTransform(np.float32([[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]]), dst)
        top = cv2.warpPerspective(product, Ht, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        a_top = cv2.warpPerspective(top_mask_src, Ht, (w, h))
        canvas = _over(canvas, np.clip(top * gain, 0, 255), _soft(a_top, 1))

    canvas = _over(canvas, scene, _soft(keep, 1))
    return np.clip(canvas, 0, 255).astype(np.uint8)


def layers_preview(scene: np.ndarray, t: SceneTemplate, old: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Editor view: blue = old product (replaced), green = kept on top."""
    out = scene.astype(np.float32)
    out[old > 0] = out[old > 0] * 0.45 + np.array([255, 120, 40]) * 0.55
    out[keep > 0] = out[keep > 0] * 0.45 + np.array([60, 220, 60]) * 0.55
    img = out.astype(np.uint8)
    cv2.polylines(img, [np.int32(skirt_quad(t))], True, (0, 220, 255), 2)
    return img


# ---------------------------------------------------------------- auto set-up


def trace_in_box(scene: np.ndarray, box: list[float], max_points: int = 40) -> Optional[list[list[float]]]:
    """Exact outline of the thing inside a box (GrabCut: the box edge is
    background, the object is what stands out inside it). Fractions of the scene."""
    h, w = scene.shape[:2]
    x0, y0, x1, y1 = box
    # pad a little: model boxes are often tight
    px, py = 0.08 * (x1 - x0), 0.08 * (y1 - y0)
    X0, Y0 = max(int((x0 - px) * w), 0), max(int((y0 - py) * h), 0)
    X1, Y1 = min(int((x1 + px) * w), w - 1), min(int((y1 + py) * h), h - 1)
    if X1 - X0 < 8 or Y1 - Y0 < 8:
        return None
    pad = 12
    cx0, cy0 = max(X0 - pad, 0), max(Y0 - pad, 0)
    cx1, cy1 = min(X1 + pad, w - 1), min(Y1 + pad, h - 1)
    crop = scene[cy0:cy1 + 1, cx0:cx1 + 1]
    rect = (X0 - cx0, Y0 - cy0, X1 - X0, Y1 - Y0)
    mask = np.zeros(crop.shape[:2], np.uint8)
    try:
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(crop, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea) if cnts else None
    if c is None or cv2.contourArea(c) < 0.15 * (X1 - X0) * (Y1 - Y0):
        # GrabCut found next to nothing (e.g. gold arm on a busy dress): keep the
        # box itself - the scene's colour clean-up then trims old-product fabric
        # off its edges
        c = np.array([[[X0 - cx0, Y0 - cy0]], [[X1 - cx0, Y0 - cy0]], [[X1 - cx0, Y1 - cy0]], [[X0 - cx0, Y1 - cy0]]])
    eps = 0.003 * cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, eps, True)
    while len(approx) > max_points:
        eps *= 1.4
        approx = cv2.approxPolyDP(c, eps, True)
    return [[(p[0][0] + cx0) / w, (p[0][1] + cy0) / h] for p in approx]


def apply_found(t: SceneTemplate, scene: np.ndarray, found: dict[str, list[list[float]]],
                product: str, top_piece: Optional[str], keep: list[str]) -> list[str]:
    """Turn boxes found by the vision model into the scene's marks. Returns notes."""
    notes = []
    boxes = found.get(product) or []
    if boxes:
        # the biggest box is the product
        x0, y0, x1, y1 = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        t.cx, t.rx = (x0 + x1) / 2, max((x1 - x0) / 2, 0.05)
        t.top, t.bottom = y0, max(y1, y0 + 0.06)
    else:
        notes.append(f"Couldn't find the {product} - drag the oval yourself.")
    if top_piece:
        tb = found.get(top_piece) or []
        faces = found.get("face") or []
        if tb:
            x0, y0, x1, y1 = max(tb, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            if faces:  # neckline never above the chin
                y0 = max(y0, max(f[3] for f in faces))
            if y1 - y0 > 0.03:
                t.top_box = [x0, y0, x1, y1]
        else:
            notes.append(f"Couldn't find the {top_piece} - turn on the top-piece box yourself if needed.")
    # Small models often repeat a box for several names (the chest box labelled
    # "hand", the face box labelled "necklace"). A keep box that is really the
    # product, top piece or face is ignored.
    taken = [b for k in (product, top_piece or "", "face") for b in (found.get(k) or [])]

    def _iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0

    outlines, missing = [], []
    for label in keep:
        got = [b for b in (found.get(label) or []) if label == "face" or all(_iou(b, o) < 0.6 for o in taken)]
        if not got:
            missing.append(label)
        for b in got:
            poly = trace_in_box(scene, b)
            if poly and len(poly) >= 3:
                outlines.append(poly)
    t.keep_outlines = outlines
    if missing:
        notes.append("Not found: " + ", ".join(missing) + ". Outline them yourself if they should stay on top.")
    return notes


# ---------------------------------------------------------------- storage


class SceneStore:
    """<shop>/scenes/<id>/ : scene.jpg, template.json and cached layers."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def dir(self, scene_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{10}", scene_id or ""):
            raise FileNotFoundError(scene_id)
        d = self.root / scene_id
        if not (d / "template.json").is_file():
            raise FileNotFoundError(scene_id)
        return d

    def list(self) -> list[SceneTemplate]:
        out = []
        for d in self.root.iterdir():
            try:
                out.append(self.get(d.name))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda t: t.created, reverse=True)

    def get(self, scene_id: str) -> SceneTemplate:
        return SceneTemplate.from_dict(json.loads((self.dir(scene_id) / "template.json").read_text(encoding="utf-8")))

    def create(self, img: Image.Image, name: str) -> SceneTemplate:
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        sid = uuid.uuid4().hex[:10]
        d = self.root / sid
        d.mkdir(parents=True)
        img.save(d / "scene.jpg", "JPEG", quality=94)
        t = SceneTemplate(id=sid, name=(name or "Scene").strip()[:60], width=img.width, height=img.height,
                          created=time.time())
        self.save(t)
        return t

    def save(self, t: SceneTemplate) -> SceneTemplate:
        d = self.root / t.id
        tmp = d / "template.json.tmp"
        tmp.write_text(json.dumps(t.to_dict(), indent=1), encoding="utf-8")
        os.replace(tmp, d / "template.json")
        self._build(t)
        return t

    def _build(self, t: SceneTemplate) -> None:
        """Pre-compute masks and the empty plate so each render is quick."""
        d = self.root / t.id
        scene = cv2.imread(str(d / "scene.jpg"))
        old, keep = analyse(scene, t)
        cv2.imwrite(str(d / "keep.png"), keep)
        cv2.imwrite(str(d / "plate.jpg"), empty_plate(scene, old).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "layers.jpg"), layers_preview(scene, t, old, keep), [cv2.IMWRITE_JPEG_QUALITY, 85])
        thumb = cv2.resize(scene, (240, int(240 * scene.shape[0] / scene.shape[1])), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(d / "thumb.jpg"), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

    def delete(self, scene_id: str) -> None:
        import shutil

        shutil.rmtree(self.dir(scene_id), ignore_errors=True)

    def file(self, scene_id: str, name: str) -> Path:
        if name not in {"scene.jpg", "layers.jpg", "thumb.jpg"}:
            raise FileNotFoundError(name)
        return self.dir(scene_id) / name

    def render(self, scene_id: str, product: Image.Image, cut: Image.Image) -> Image.Image:
        """product: RGB photo; cut: RGBA cut-out of it (same size)."""
        t = self.get(scene_id)
        d = self.dir(scene_id)
        scene = cv2.imread(str(d / "scene.jpg"))
        plate = cv2.imread(str(d / "plate.jpg")).astype(np.float32)
        keep = cv2.imread(str(d / "keep.png"), cv2.IMREAD_GRAYSCALE)
        bgr = cv2.cvtColor(np.asarray(product.convert("RGB")), cv2.COLOR_RGB2BGR)
        alpha = np.asarray(cut.convert("RGBA"))[:, :, 3].copy()
        if alpha.shape != bgr.shape[:2]:
            alpha = cv2.resize(alpha, (bgr.shape[1], bgr.shape[0]))
        out = render(t, scene, plate, keep, bgr, alpha)
        return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
