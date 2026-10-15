"""Swap the dress in a photo of a dressed idol for another dress, from its flat photo.

The worn dress in the reference already has the right shape, folds and light.
The new dress's flat photo is bent onto that shape (skirt: rings from the waist
out to the hem; bodice: onto the old bodice), the old dress's soft shading is
laid over it, and the idol's arms, hands and hair stay on top.

    python swap.py ref_blue.png dress.jpg out.png swap.json [bare_idol.png]

With a bare-idol photo as the last argument, the dress goes onto that photo
instead; the reference only lends the dress's shape and shading.
"""
import json
import math
import sys

import cv2
import numpy as np

REF, DRESS, OUT, CFG = sys.argv[1:5]
BASE = sys.argv[5] if len(sys.argv) > 5 else None
c = json.load(open(CFG))
ref = cv2.imread(REF)
base = None
if BASE:
    # A photo of the same idol WITHOUT a dress: the reference only lends the
    # dress's shape and shading. Line the reference up with it by the eyes.
    base = cv2.imread(BASE)
    (rx1, ry1), (rx2, ry2) = c["align"]["ref_eyes"]
    (bx1, by1), (bx2, by2) = c["align"]["base_eyes"]
    k = math.hypot(bx2 - bx1, by2 - by1) / math.hypot(rx2 - rx1, ry2 - ry1)
    rmx, rmy, bmx, bmy = (rx1 + rx2) / 2, (ry1 + ry2) / 2, (bx1 + bx2) / 2, (by1 + by2) / 2
    M = np.float32([[k, 0, bmx - k * rmx], [0, k, bmy - k * rmy]])
    ref = cv2.warpAffine(ref, M, (base.shape[1], base.shape[0]), borderMode=cv2.BORDER_REPLICATE)

    def T(p):
        return [p[0] * k + M[0, 2], p[1] * k + M[1, 2]]

    sk = c["skirt"]
    sk["waist_centre"], sk["hem_centre"] = T(sk["waist_centre"]), T(sk["hem_centre"])
    sk["waist_radii"] = [v * k for v in sk["waist_radii"]]
    sk["hem_radii"] = [v * k for v in sk["hem_radii"]]
    c["bodice"]["quad"] = [T(p) for p in c["bodice"]["quad"]]
    c["old_dress_outline"] = [T(p) for p in c["old_dress_outline"]]
    if c["align"].get("base_v_neck"):
        c["bodice"]["v_neck"] = c["align"]["base_v_neck"]
    if c["align"].get("base_straps"):
        c["bodice"]["straps"] = c["align"]["base_straps"]
    c["keep_on_top"] = c["align"].get("base_keep_on_top") or [[T(p) for p in poly] for poly in c["keep_on_top"]]
H, W = ref.shape[:2]
dress = cv2.imread(DRESS)
d = c["dress_photo"]

# ---- dress photo: background -> alpha, centre and radius of the round skirt
bg = np.median(np.concatenate([dress[:8].reshape(-1, 3), dress[-8:].reshape(-1, 3)]), axis=0)
fab = (np.abs(dress.astype(int) - bg).sum(axis=2) > 60).astype(np.uint8) * 255
fab = cv2.morphologyEx(fab, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
fab = cv2.erode(fab, np.ones((3, 3), np.uint8))
ys, xs = np.nonzero(fab)
CX, CY = d.get("centre") or (xs.mean(), ys.mean())
R = d.get("radius") or math.sqrt(len(xs) / math.pi)
dress_a = np.dstack([dress, fab])


# ---- skirt: polar grid in the flat photo -> scene positions
s = c["skirt"]
Cw, Rw = np.array(s["waist_centre"], float), np.array(s["waist_radii"], float)
Co, Ro = np.array(s["hem_centre"], float), np.array(s["hem_radii"], float)
r_in = s.get("inner_px", 70)          # skirt radius hidden under the bodice in the flat photo
gamma = s.get("gamma", 0.85)
NA, NR = 96, 28


def scene_pt(theta, f):
    """theta: angle in the flat photo (0 = right, 90 = down = front); f 0..1 waist..hem."""
    g = f ** gamma
    cen = Cw + (Co - Cw) * g
    rad = Rw + (Ro - Rw) * g
    return cen + rad * np.array([math.cos(theta), math.sin(theta)])


out = ref.astype(np.float32).copy()
layer = np.zeros((H, W, 3), np.float32)
alpha = np.zeros((H, W), np.float32)


def warp_tri(src_img, src_tri, dst_tri):
    global layer, alpha
    src_tri, dst_tri = np.float32(src_tri), np.float32(dst_tri)
    x, y, w, h = cv2.boundingRect(dst_tri)
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    M = cv2.getAffineTransform(src_tri, np.float32(dst_tri - np.float32([x0, y0])))
    patch = cv2.warpAffine(src_img, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillConvexPoly(m, np.int32(np.round(dst_tri - [x0, y0])), 1)
    a = patch[..., 3].astype(np.float32) / 255 * m
    sl = (slice(y0, y1), slice(x0, x1))
    layer[sl] = layer[sl] * (1 - a[..., None]) + patch[..., :3] * a[..., None]
    alpha[sl] = np.maximum(alpha[sl], a)


# draw back half first (behind), then front half
order = sorted(range(NA), key=lambda j: math.sin(2 * math.pi * (j + 0.5) / NA))
for j in order:
    for i in range(NR):
        quad_src, quad_dst = [], []
        for (jj, ii) in ((j, i), (j + 1, i), (j + 1, i + 1), (j, i + 1)):
            th = 2 * math.pi * jj / NA
            rr = r_in + (R * 1.03 - r_in) * ii / NR
            # in the flat photo the bodice lies on the back half of the skirt; the
            # skirt is round and symmetric, so the back half is taken from the
            # mirrored front half
            ths = th if math.sin(th) >= 0 else -th
            if s.get("dodge_bodice", True) and rr > 1:
                # in the flat photo the bodice also lies over the skirt just below
                # its sides: squeeze the angles into the uncovered part at the same
                # radius (the skirt's rings repeat all the way round). A smooth
                # squeeze, so no triangle collapses.
                y_cut = d["bodice_box"][3] - CY + s.get("dodge_gap_px", 22)
                half_w = (d["bodice_box"][2] - d["bodice_box"][0]) / 2 + 10
                a_min = math.asin(min(1.0, y_cut / rr)) if rr > y_cut else math.pi / 2 - 0.05
                fade = min(max((rr - half_w) / 60.0, 0.0), 1.0)    # beyond the bodice: no squeeze
                a_min *= (1 - fade)
                ths = a_min + ths * (math.pi - 2 * a_min) / math.pi
            quad_src.append((CX + rr * math.cos(ths), CY + rr * math.sin(ths)))
            quad_dst.append(scene_pt(th, ii / NR))
        warp_tri(dress_a, [quad_src[0], quad_src[1], quad_src[2]], [quad_dst[0], quad_dst[1], quad_dst[2]])
        warp_tri(dress_a, [quad_src[0], quad_src[2], quad_src[3]], [quad_dst[0], quad_dst[2], quad_dst[3]])
skirt_alpha = alpha.copy()

# ---- bodice: the flat bodice onto the old bodice (bilinear over a grid)
b = c["bodice"]
bx0, by0, bx1, by1 = d["bodice_box"]
tl, tr, br, bl = [np.array(p, float) for p in b["quad"]]   # in the scene
bulge = b.get("bulge", 0.06)
GX, GY = 16, 12
bod_layer_start = layer.copy(), alpha.copy()


def bpt(u, v):
    top = tl + (tr - tl) * u
    bot = bl + (br - bl) * u
    p = top + (bot - top) * v
    # a little roundness: the middle of the chest comes forward/down slightly
    p[1] += bulge * (bot[1] - top[1]) * math.sin(math.pi * u) * 0.3
    return p


before_bodice = (layer.copy(), alpha.copy())
for gy in range(GY):
    for gx in range(GX):
        us = [gx / GX, (gx + 1) / GX]
        vs = [gy / GY, (gy + 1) / GY]
        src = [(bx0 + (bx1 - bx0) * u, by0 + (by1 - by0) * v) for (u, v) in ((us[0], vs[0]), (us[1], vs[0]), (us[1], vs[1]), (us[0], vs[1]))]
        dst = [bpt(u, v) for (u, v) in ((us[0], vs[0]), (us[1], vs[0]), (us[1], vs[1]), (us[0], vs[1]))]
        solid = np.dstack([dress, np.full(dress.shape[:2], 255, np.uint8)])  # bodice: no background holes
        warp_tri(solid, src[:3], dst[:3])
        warp_tri(solid, [src[0], src[2], src[3]], [dst[0], dst[2], dst[3]])

# keep the new bodice only where the old top was (its neckline and armholes)
hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV)
vq = np.zeros((H, W), np.uint8)
cv2.fillPoly(vq, [np.int32(b["quad"])], 255)
lo, hi = b.get("old_top_hue", [100, 135])        # OpenCV hue 0-180; blue ~ 100-130
rf = ref.astype(int)
bluish = (rf[..., 0] > rf[..., 2] + 25) & (rf[..., 0] > rf[..., 1] + 10)   # also dark/shadowed blue
if b.get("old_top_colour") == "red":
    # red top: red fabric plus its gold trims count as the top (inside the box)
    reddish = (rf[..., 2] > rf[..., 1] + 60) & (rf[..., 2] > rf[..., 0] + 40)
    top_px = reddish.astype(np.uint8) * 255
else:
    top_px = (((hsv[..., 0] >= lo) & (hsv[..., 0] <= hi) & (hsv[..., 1] > 90)) | bluish).astype(np.uint8) * 255
top_px = cv2.bitwise_and(top_px, vq)
top_px = cv2.morphologyEx(top_px, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
cnts, _ = cv2.findContours(top_px, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
top_mask = np.zeros((H, W), np.uint8)
cv2.drawContours(top_mask, [c_ for c_ in cnts if cv2.contourArea(c_) > 500], -1, 255, -1)
# the old waistband (gold, not blue) belongs to the top too: fill the bottom band
qb = int(max(p[1] for p in b["quad"]))
band = b.get("waistband_px", 40)
qx0 = int(min(p[0] for p in b["quad"][2:]))
qx1 = int(max(p[0] for p in b["quad"][2:]))
top_mask[qb - band: qb + 1, qx0: qx1 + 1] = 255
top_mask = cv2.dilate(top_mask, np.ones((b.get("grow_px", 7),) * 2, np.uint8))
tm = cv2.GaussianBlur(top_mask.astype(np.float32) / 255, (5, 5), 0)
in_quad = (vq > 0).astype(np.float32)
l0, a0 = before_bodice
w_ = (tm * in_quad)[..., None]
layer = layer * w_ + l0 * (1 - w_) * 1.0 + 0 * layer
layer = np.where(in_quad[..., None] > 0, layer, l0 if False else layer)
alpha = np.where(in_quad > 0, np.maximum(a0, tm), alpha)
# where the quad held bodice but the old top wasn't, use the skirt layer underneath
layer = np.where((in_quad[..., None] > 0) & (tm[..., None] < 0.5), l0, layer)
# upper part of the top area that isn't the old top = neck and chest: show the
# idol there, not the back of the skirt behind him
qt = int(min(p[1] for p in b["quad"]))
upper = np.zeros((H, W), bool)
upper[qt: qt + int((qb - qt) * b.get("neck_share", 0.5))] = True
alpha = np.where((in_quad > 0) & upper & (tm < 0.5), 0, alpha)

# Fit the bodice photo to the top's real outline, row by row: its left and right
# edges (the gold armhole trims) land on the top's edges instead of being cut off.
if b.get("fit_rows", True):
    tmb = (tm > 0.5) & (in_quad > 0)
    rows = np.nonzero(tmb.any(axis=1))[0]
    if len(rows):
        r0, r1 = rows.min(), rows.max()
        mapx = np.full((H, W), -1, np.float32)
        mapy = np.full((H, W), -1, np.float32)
        ys_ = np.arange(r0, r1 + 1)
        L = np.array([np.nonzero(tmb[y])[0].min() if tmb[y].any() else np.nan for y in ys_])
        R = np.array([np.nonzero(tmb[y])[0].max() if tmb[y].any() else np.nan for y in ys_])
        ok = ~np.isnan(L)
        L = np.interp(ys_, ys_[ok], L[ok]); R = np.interp(ys_, ys_[ok], R[ok])
        # smooth edges: the colour mask is ragged, a garment edge is not
        from scipy.ndimage import median_filter, gaussian_filter1d
        L = gaussian_filter1d(median_filter(L, 15), 4); R = gaussian_filter1d(median_filter(R, 15), 4)
        smooth = np.zeros((H, W), bool)
        for i, y in enumerate(ys_):
            lft, rgt = int(round(L[i])), int(round(R[i]))
            if rgt - lft < 2:
                continue
            u = (np.arange(lft, rgt + 1) - lft) / (rgt - lft)
            v = (y - r0) / max(r1 - r0, 1)
            mapx[y, lft:rgt + 1] = bx0 + u * (bx1 - bx0)
            mapy[y, lft:rgt + 1] = by0 + v * (by1 - by0)
            smooth[y, lft:rgt + 1] = True
        # keep the neckline hole from the old top, but use the smooth outer edges
        hole = smooth & ~tmb & ~cv2.dilate(tmb.astype(np.uint8), np.ones((1, 9), np.uint8)).astype(bool)
        neck_hole = np.zeros((H, W), bool)
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats(hole.astype(np.uint8))
        for k_ in range(1, n_):
            if st_[k_, cv2.CC_STAT_AREA] > 300:
                neck_hole |= lab_ == k_
        tm = np.where(in_quad > 0, (smooth & ~neck_hole).astype(np.float32), tm)
        tm = cv2.GaussianBlur(tm, (3, 3), 0)
        alpha = np.where((in_quad > 0) & (tm > 0.5), np.maximum(alpha, tm), alpha)
        fitted = cv2.remap(dress, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        w2 = (tm * in_quad * (mapx >= 0))[..., None]
        layer = layer * (1 - w2) + fitted * w2

# Shoulder straps (cap sleeves): the vest goes over the shoulders. Each strap is a
# polygon in the final image; the bodice photo's side edge (its gold trim) runs
# along the strap's outer edge, plain fabric towards the neck.
strap_mask = np.zeros((H, W), np.uint8)
straps = b.get("straps") or []
if straps:
    sx = (bx1 - bx0) / max(W * 0.12, 1)
    rows_fit = np.nonzero(((tm > 0.5) & (in_quad > 0)).any(axis=1))[0]
    if len(rows_fit):
        y_mid = rows_fit.min() + 5
        xs_mid = np.nonzero((tm[y_mid] > 0.5) & (in_quad[y_mid] > 0))[0]
        if len(xs_mid) > 2:
            sx = (bx1 - bx0) / (xs_mid.max() - xs_mid.min())
    mx = np.full((H, W), -1, np.float32)
    my = np.full((H, W), -1, np.float32)
    for side, poly in enumerate(straps):
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [np.int32(poly)], 255)
        strap_mask |= m
        ys_s = np.nonzero(m.any(axis=1))[0]
        for y in ys_s:
            xs_ = np.nonzero(m[y])[0]
            if side == 0:     # left of the picture: outer edge = smallest x
                mx[y, xs_] = bx0 + (xs_ - xs_.min()) * sx
            else:
                mx[y, xs_] = bx1 - (xs_.max() - xs_) * sx
            my[y, xs_] = by0 + b.get("top_px", 25) + (y - ys_s.min()) * sx * 0.6
    strap_img = cv2.remap(dress, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    sm = cv2.GaussianBlur(strap_mask.astype(np.float32) / 255, (3, 3), 0)
    layer = layer * (1 - sm[..., None]) + strap_img * sm[..., None]
    alpha = np.maximum(alpha, sm)

# V neckline: cut a V out of the vest (the idol's chest shows there) and edge both
# sides of the V with a strip of the dress's own gold trim.
vn = b.get("v_neck")
if vn:
    L_, R_, B_ = [np.float32(vn[k]) for k in ("left", "right", "bottom")]
    v_mask = np.zeros((H, W), np.uint8)
    top_l = L_ + np.float32([0, -40]); top_r = R_ + np.float32([0, -40])
    cv2.fillPoly(v_mask, [np.int32([top_l, L_, B_, R_, top_r])], 255)
    vm = cv2.GaussianBlur(v_mask.astype(np.float32) / 255, (3, 3), 0)
    alpha = alpha * (1 - vm)
    tx0, tx1, ty0, ty1 = vn["trim_src"]
    trim = dress[ty0:ty1, tx0:tx1]
    tw = vn.get("trim_px", 12)
    for P, Q in ((L_, B_), (R_, B_)):
        d_ = Q - P
        length = float(np.hypot(*d_))
        n_ = np.float32([-d_[1], d_[0]]) / length
        if np.dot(n_, (L_ + R_) / 2 - P) > 0:     # trim lies on the vest side, outside the V
            n_ = -n_
        strip = cv2.resize(cv2.rotate(trim, cv2.ROTATE_90_CLOCKWISE) if False else trim, (tw, max(int(length), 2)))
        src = np.float32([[0, 0], [tw, 0], [0, strip.shape[0]]])
        dstp = np.float32([P, P + n_ * tw, Q])
        M2 = cv2.getAffineTransform(src, dstp)
        warped = cv2.warpAffine(strip, M2, (W, H), flags=cv2.INTER_LINEAR)
        mk = cv2.warpAffine(np.full(strip.shape[:2], 255, np.uint8), M2, (W, H)).astype(np.float32) / 255
        mk = cv2.GaussianBlur(mk, (3, 3), 0)
        layer = layer * (1 - mk[..., None]) + warped.astype(np.float32) * mk[..., None]
        alpha = np.maximum(alpha, mk)

# ---- shading from the old dress (soft, so its pattern doesn't show through)
gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
soft = cv2.GaussianBlur(gray, (0, 0), c.get("shade_blur", 18))
inside = alpha > 0.5
ref_level = np.median(soft[inside])
shade = np.clip((soft / ref_level) ** c.get("shade_strength", 0.6), 0.55, 1.25)
layer *= shade[..., None]

# ---- old dress outside the new one: fill with the floor
region = np.zeros((H, W), np.uint8)
cv2.fillPoly(region, [np.int32(c["old_dress_outline"])], 255)
ring = cv2.dilate(region, np.ones((41, 41), np.uint8)) & ~cv2.dilate(region, np.ones((15, 15), np.uint8))
cloth = np.median(ref[ring > 0], axis=0)
# the old dress = inside the outline and clearly not the cloth it lies on
old = ((np.abs(ref.astype(int) - cloth).sum(axis=2) > c.get("cloth_tol", 45)) & (region > 0)).astype(np.uint8) * 255
old = cv2.morphologyEx(old, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
old = cv2.dilate(old, np.ones((5, 5), np.uint8))
leftover = (old > 0) & (alpha < 0.5) & ~((in_quad > 0) & upper)
if base is not None:
    leftover[:] = False          # the bare photo has no old dress to hide
plate = (base if base is not None else ref).copy()
if leftover.any():
    # fill the whole old dress area from the floor around it, then use that fill
    # only where the new dress doesn't cover
    hole = cv2.dilate(old, np.ones((15, 15), np.uint8))
    small = cv2.resize(plate, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    hs = cv2.resize(hole, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    filled = cv2.resize(cv2.inpaint(small, hs, 9, cv2.INPAINT_TELEA), (W, H), interpolation=cv2.INTER_CUBIC)
    filled = cv2.GaussianBlur(filled, (0, 0), 3).astype(np.float32)
    # the cloth's own fine texture back on top of the smooth fill
    # the cloth's fine grain, so the fill doesn't look smoother than the cloth
    grain = np.random.default_rng(0).normal(0, c.get("grain", 3.0), (H, W, 1)).astype(np.float32)
    filled = np.clip(filled + grain, 0, 255).astype(np.uint8)
    plate[leftover] = filled[leftover]

# soft shadow of the new skirt on the floor
sh = cv2.GaussianBlur(cv2.dilate((skirt_alpha > 0.5).astype(np.float32), np.ones((5, 5), np.uint8)), (0, 0), 6)
sh = np.vstack([np.zeros((5, W), np.float32), sh[:-5]])   # shift down, no wrap-around
plate = (plate.astype(np.float32) * (1 - 0.25 * sh[..., None] * (alpha[..., None] < 0.5))).astype(np.uint8)

a = cv2.GaussianBlur(alpha, (3, 3), 0)[..., None]
out = plate.astype(np.float32) * (1 - a) + layer * a

# ---- the idol stays on top: arms, hands, ball, hair
keep = np.zeros((H, W), np.uint8)
for poly in c["keep_on_top"]:
    cv2.fillPoly(keep, [np.int32(poly)], 255)
if base is not None and c.get("keep_trim_cloth", True):
    # outlines may be loose on the outside: drop the floor cloth from them, so the
    # arm's real edge is used (the cloth colour is learnt from the photo's border)
    edge = np.concatenate([base[-40:].reshape(-1, 3), base[:, :20].reshape(-1, 3), base[:, -20:].reshape(-1, 3)])
    cloth_col = np.median(edge, axis=0)
    is_cloth = (np.abs(base.astype(int) - cloth_col).sum(axis=2) < c.get("cloth_tol", 45)).astype(np.uint8)
    is_cloth = cv2.morphologyEx(is_cloth, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    keep[is_cloth > 0] = 0
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
keep[strap_mask > 0] = 0
# a soft contact shadow round what stays on top (hands resting on the dress)
ring = cv2.GaussianBlur(keep.astype(np.float32) / 255, (0, 0), c.get("contact_shadow_px", 6))
ring = np.clip(ring - keep.astype(np.float32) / 255, 0, 1)
out = out * (1 - c.get("contact_shadow", 0.45) * ring[..., None])
keep = cv2.GaussianBlur(keep.astype(np.float32) / 255, (3, 3), 0)[..., None]
out = out * (1 - keep) + (base if base is not None else ref).astype(np.float32) * keep
cv2.imwrite(OUT, np.clip(out, 0, 255).astype(np.uint8))
print("saved", OUT)
