"""Template mockups: put a REAL dress photo onto a ready-made idol scene.

Nothing is redrawn by AI. The dress pixels are the seller's own photo, only
reshaped (perspective) to lie on the scene, so colours and embroidery stay exact.
Runs in a couple of seconds on any laptop.

    python mockup.py templates/gopal1 my_dress.jpg out.png [--debug]

A template folder holds:
    scene.png      the finished scene (idol + setting), e.g. made once with any AI tool
    template.json  where things are, see templates/gopal1/template.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ------------------------------------------------------------------ cut-out


def cut_out(img: np.ndarray) -> np.ndarray:
    """Alpha mask of the product. Uses rembg when installed, otherwise a
    plain-background cut (works for dresses shot on black/white cloth)."""
    try:
        if os.environ.get("MOCKUP_NO_REMBG"):
            raise ImportError
        from rembg import new_session, remove  # type: ignore

        sess = new_session("isnet-general-use")
        rgba = remove(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), session=sess)
        return np.asarray(rgba)[:, :, 3]
    except Exception:  # noqa: BLE001 - no rembg / no model download
        pass
    # Pad with the background colour so a dress touching the photo's edge
    # doesn't get the edge glued onto it.
    pad = 24
    edge = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3),
                           img[:, :4].reshape(-1, 3), img[:, -4:].reshape(-1, 3)])
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                             value=[int(v) for v in np.median(edge, axis=0)])
    h, w = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[:8].reshape(-1, 3), lab[-8:].reshape(-1, 3),
                             lab[:, :8].reshape(-1, 3), lab[:, -8:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(lab - bg, axis=2)
    noise = np.percentile(np.linalg.norm(border - bg, axis=1), 95)
    m = (dist > max(18.0, noise * 2.5)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    # keep the biggest piece and fill its holes
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m = (lbl == big).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(m)
    cv2.drawContours(filled, cnts, -1, 255, -1)
    return cv2.GaussianBlur(filled, (3, 3), 0)[pad:-pad, pad:-pad]


# ------------------------------------------------------------------ helpers


def poly_mask(shape, polys) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    for p in polys:
        cv2.fillPoly(m, [np.array(p, np.int32)], 255)
    return m


def fabric_mask(scene: np.ndarray, colours: list[dict]) -> np.ndarray:
    """Pixels that belong to the template's own dress (by colour), so they can
    be dropped from the idol layer where the idol touches the dress."""
    hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)
    out = np.zeros(scene.shape[:2], np.uint8)
    for c in colours:
        lo, hi = np.array(c["lo"], np.uint8), np.array(c["hi"], np.uint8)
        out |= cv2.inRange(hsv, lo, hi)
    return out


def feather(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask.astype(np.float32) / 255
    k = px * 2 + 1
    return cv2.GaussianBlur(mask, (k, k), 0).astype(np.float32) / 255


def over(base: np.ndarray, top: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    a = alpha[..., None]
    return (top.astype(np.float32) * a + base.astype(np.float32) * (1 - a)).astype(np.float32)


def empty_plate(scene: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """The scene with the old dress removed (table/background filled in).
    Done small and smooth: the table is plain, and most of it gets covered."""
    small = cv2.resize(scene, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    hs = cv2.resize(hole, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    hs = cv2.dilate(hs, np.ones((5, 5), np.uint8))
    filled = cv2.inpaint(small, hs, 9, cv2.INPAINT_TELEA)
    filled = cv2.GaussianBlur(filled, (9, 9), 0)
    big = cv2.resize(filled, (scene.shape[1], scene.shape[0]), interpolation=cv2.INTER_CUBIC)
    grain = np.random.default_rng(0).normal(0, 1.6, scene.shape).astype(np.float32)
    big = np.clip(big.astype(np.float32) + grain, 0, 255)
    a = feather(cv2.dilate(hole, np.ones((9, 9), np.uint8)), 6)
    return over(scene, big, a)


# ------------------------------------------------------------------ main steps


def skirt_warp(dress, alpha, t, size):
    """Lay the whole round dress on the floor in perspective: the photo's square
    goes to a trapezoid (far edge narrower), centre of the dress at the waist."""
    ys, xs = np.nonzero(alpha > 128)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    src = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    dst = np.float32(t["skirt"]["quad"])  # back-left, back-right, front-right, front-left
    H = cv2.getPerspectiveTransform(src, dst)
    w, h = size
    # The top piece is shown standing on the chest (see bodice_warp). Where it lies
    # on the flat photo, show the skirt that sits under it instead: the same
    # dress's embroidery from the opposite side of the circle. Mostly hidden
    # behind the idol, it just stops the top piece appearing twice.
    hide = t["bodice"].get("src_outline")
    if hide:
        bw, bh = x1 - x0, y1 - y0
        pm = poly_mask(dress.shape, [[[x0 + u * bw, y0 + v * bh] for u, v in hide]])
        pm = cv2.dilate(pm, np.ones((25, 25), np.uint8))
        centre = ((x0 + x1) / 2, (y0 + y1) / 2)
        R = cv2.getRotationMatrix2D(centre, 180, 1.0)
        flipped = cv2.warpAffine(dress, R, (dress.shape[1], dress.shape[0]), flags=cv2.INTER_LINEAR)
        soft = feather(pm, 6)[..., None]
        dress = (flipped * soft + dress * (1 - soft)).astype(np.uint8)
    img = cv2.warpPerspective(dress, H, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    a = cv2.warpPerspective(alpha, H, (w, h), flags=cv2.INTER_LINEAR)
    return img, a


def bodice_warp(dress, alpha, t, size):
    """The dress's top piece stands up on the idol's chest."""
    b = t["bodice"]
    x0, y0, x1, y1 = b["src_box"]  # in the dress photo, as fractions of the cut-out box
    ys, xs = np.nonzero(alpha > 128)
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = bx1 - bx0, by1 - by0
    sx0, sx1 = bx0 + x0 * bw, bx0 + x1 * bw
    sy0, sy1 = by0 + y0 * bh, by0 + y1 * bh
    src = np.float32([[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]])
    dst = np.float32(b["quad"])
    H = cv2.getPerspectiveTransform(src, dst)
    w, h = size
    img = cv2.warpPerspective(dress, H, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    # shape of the top piece: its outline in the dress photo, as fractions too
    outline = [[bx0 + u * bw, by0 + v * bh] for u, v in b["src_outline"]]
    pm = poly_mask(dress.shape, [outline])
    pm = cv2.bitwise_and(pm, alpha)
    a = cv2.warpPerspective(pm, H, (w, h), flags=cv2.INTER_LINEAR)
    return img, a


def shading(scene, region, strength):
    """Large-scale light and folds from the template's old dress (very blurred,
    so none of its pattern carries over)."""
    lum = cv2.cvtColor(scene, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    sel = region > 0
    lum_f = cv2.GaussianBlur(lum, (0, 0), 28)
    ref = np.median(lum_f[sel]) if sel.any() else 128
    gain = 1 + strength * (lum_f / max(ref, 1) - 1)
    return np.clip(gain, 0.7, 1.2)


def make(template_dir: Path, dress_path: Path, out_path: Path, debug: bool = False) -> dict:
    t0 = time.time()
    t = json.loads((template_dir / "template.json").read_text())
    scene = cv2.imread(str(template_dir / t.get("scene", "scene.png")))
    dress = cv2.imread(str(dress_path))
    if scene is None or dress is None:
        sys.exit("Couldn't read the template scene or the dress photo")
    h, w = scene.shape[:2]

    alpha = cut_out(dress)
    # trim the outermost pixels so no background colour fringes the scalloped edge
    alpha = cv2.erode(alpha, np.ones((5, 5), np.uint8))
    t_cut = time.time() - t0

    # layers from the template
    fabric = fabric_mask(scene, t["template_fabric_colours"])
    idol = poly_mask(scene.shape, t["idol"]["polygons"])
    keep_on_fabric = poly_mask(scene.shape, t["idol"].get("always_keep", []))
    idol = cv2.bitwise_and(idol, cv2.bitwise_not(cv2.bitwise_and(fabric, cv2.bitwise_not(keep_on_fabric))))
    idol = cv2.morphologyEx(idol, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    idol = cv2.morphologyEx(idol, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    old_dress = poly_mask(scene.shape, t["old_dress"]["polygons"])
    old_dress = cv2.bitwise_and(old_dress, cv2.bitwise_not(idol))

    plate = empty_plate(scene, old_dress)

    # new dress
    skirt, a_skirt = skirt_warp(dress, alpha, t, (w, h))
    top, a_top = bodice_warp(dress, alpha, t, (w, h))

    # soft shadow of the skirt on the table
    sh = t["skirt"].get("shadow", {"dx": 0, "dy": 14, "blur": 31, "opacity": 0.35})
    sm = np.roll(a_skirt, (sh["dy"], sh["dx"]), axis=(0, 1))
    k = sh["blur"] | 1
    sm = cv2.GaussianBlur(sm, (k, k), 0).astype(np.float32) / 255 * sh["opacity"]
    canvas = plate * (1 - sm[..., None])

    region = cv2.bitwise_or(a_skirt, old_dress)
    gain = shading(scene, old_dress, t.get("shading", 0.5))[..., None]
    canvas = over(canvas, np.clip(skirt * gain, 0, 255), feather(a_skirt, 1))
    canvas = over(canvas, np.clip(top * gain, 0, 255), feather(a_top, 1))

    # idol on top (face, crown, hair, arms, hands, jewellery)
    canvas = over(canvas, scene, feather(idol, 1))

    out = np.clip(canvas, 0, 255).astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), out)
    if debug:
        dbg = scene.copy()
        dbg[idol > 0] = (dbg[idol > 0] * 0.4 + np.array([0, 255, 0]) * 0.6).astype(np.uint8)
        dbg[(old_dress > 0) & (idol == 0)] = (dbg[(old_dress > 0) & (idol == 0)] * 0.5 + np.array([255, 0, 0]) * 0.5).astype(np.uint8)
        cv2.polylines(dbg, [np.int32(t["skirt"]["quad"])], True, (0, 255, 255), 2)
        cv2.polylines(dbg, [np.int32(t["bodice"]["quad"])], True, (0, 0, 255), 2)
        cv2.imwrite(str(out_path.with_name(out_path.stem + "_layers.png")), dbg)
        cv2.imwrite(str(out_path.with_name(out_path.stem + "_cutout.png")), cv2.merge([*cv2.split(dress), alpha]))
    return {"seconds": round(time.time() - t0, 2), "cutout_seconds": round(t_cut, 2), "out": str(out_path)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", type=Path)
    ap.add_argument("dress", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--debug", action="store_true", help="also save the layer map and cut-out")
    a = ap.parse_args()
    print(make(a.template, a.dress, a.out, a.debug))
