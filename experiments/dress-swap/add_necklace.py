"""Lift the necklace out of one photo and lay it on a finished (dressed) image.

    python add_necklace.py dressed.png with_necklace.png out.png necklace.json

The necklace's pearls and stones are picked out of the photo by colour (the gold
body between them is left behind), scaled and moved by the eyes, and laid on top
with a soft shadow.
"""
import json
import math
import sys

import cv2
import numpy as np

DST, SRC, OUT, CFG = sys.argv[1:5]
c = json.load(open(CFG))
dst = cv2.imread(DST)
src = cv2.imread(SRC)
H, W = dst.shape[:2]

# 1. the necklace in the source photo
area = np.zeros(src.shape[:2], np.uint8)
cv2.fillPoly(area, [np.int32(c["outline"])], 255)
if c.get("lies_on") == "blue":
    # easiest case: the necklace lies on a plain blue top, so it is everything
    # inside the outline that isn't blue
    f = src.astype(int)
    blue = ((f[..., 0] > f[..., 2] + 25) & (f[..., 0] > f[..., 1] + 5)) | ((f[..., 0] > f[..., 2] + 8) & (f[..., 0] >= f[..., 1]) & (f.sum(axis=2) < 260))
    neck = ((~blue) & (area > 0)).astype(np.uint8) * 255
    neck = cv2.morphologyEx(neck, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    neck = cv2.morphologyEx(neck, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
elif c.get("lies_on") == "red":
    f = src.astype(int)
    red = (f[..., 2] > f[..., 1] + 60) & (f[..., 2] > f[..., 0] + 40)
    gold_trim = np.zeros(src.shape[:2], bool)
    for poly in c.get("not_necklace", []):        # e.g. the vest's gold trims
        m_ = np.zeros(src.shape[:2], np.uint8); cv2.fillPoly(m_, [np.int32(poly)], 255); gold_trim |= m_ > 0
    neck = ((~red) & ~gold_trim & (area > 0)).astype(np.uint8) * 255
    neck = cv2.morphologyEx(neck, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    neck = cv2.morphologyEx(neck, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
else:
    neck = None
hsv = cv2.cvtColor(src, cv2.COLOR_BGR2HSV).astype(int)
h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
pearl = (s < c.get("pearl_max_sat", 70)) & (v > c.get("pearl_min_val", 150))
gold = (h >= 12) & (h <= 32) & (s >= 70)
stone = (s > 90) & ~gold & (v > 40)
if neck is None:   # necklace on bare gold skin: harder, pick pearls and stones by colour
    neck = ((pearl | stone) & (area > 0)).astype(np.uint8) * 255
    neck = cv2.morphologyEx(neck, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    near = cv2.dilate(neck, np.ones((5, 5), np.uint8))
    neck = cv2.bitwise_or(neck, ((near > 0) & gold & (area > 0)).astype(np.uint8) * 255)
    neck = cv2.morphologyEx(neck, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

# 2. line the source up with the finished image by the eyes
(sx1, sy1), (sx2, sy2) = c["src_eyes"]
(dx1, dy1), (dx2, dy2) = c["dst_eyes"]
k = math.hypot(dx2 - dx1, dy2 - dy1) / math.hypot(sx2 - sx1, sy2 - sy1) * c.get("scale", 1.0)
smx, smy, dmx, dmy = (sx1 + sx2) / 2, (sy1 + sy2) / 2, (dx1 + dx2) / 2, (dy1 + dy2) / 2
off = c.get("nudge", [0, 0])
# scale round the top of the necklace (where it sits on the neck), not the eyes
top = min(p[1] for p in c["outline"])
k0 = k / c.get("scale", 1.0)
ay = dmy + k0 * (top - smy)               # where the necklace top lands at scale 1
M = np.float32([[k, 0, dmx - k * smx + off[0]], [0, k, ay - k * top + off[1]]])
piece = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR)
mask = cv2.warpAffine(neck, M, (W, H), flags=cv2.INTER_LINEAR).astype(np.float32) / 255
mask = cv2.GaussianBlur(mask, (3, 3), 0)

# 3. soft shadow just below it on the dress, then the necklace
sh = np.roll(cv2.GaussianBlur(mask, (0, 0), 2.5), (3, 1), axis=(0, 1))
out = dst.astype(np.float32) * (1 - 0.35 * sh[..., None])
out = out * (1 - mask[..., None]) + piece.astype(np.float32) * mask[..., None]
cv2.imwrite(OUT, np.clip(out, 0, 255).astype(np.uint8))
cv2.imwrite(OUT.rsplit(".", 1)[0] + "_mask.png", (mask * 255).astype(np.uint8))
print("saved", OUT)
