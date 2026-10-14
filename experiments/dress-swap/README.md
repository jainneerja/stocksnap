# Experiment: swap the dress in a photo of a dressed idol

**Idea:** start from a photo where the idol is *already wearing* a dress of the same
cut (here an AI-made reference in blue). That photo already has the right shape,
folds, light and pose. Then:

1. The new dress's flat photo is bent onto the old skirt: rings from the waist out
   to the hem (the skirt is round, so the flat photo maps ring by ring). The back
   half, which the bodice covers in the flat photo, is taken from the mirrored
   front half.
2. The flat bodice is bent onto the old top, and kept only where the old top was,
   so the new top gets the reference's neckline and armholes.
3. The old dress's soft shading is laid over the new one, so the folds and light
   match the photo.
4. Any bit of the old dress the new one doesn't cover is filled with the floor.
5. The idol's arms, hands, ball and hair are put back on top.

No AI, no GPU: about 2 seconds per dress on a laptop. The embroidery is the real
dress photo, only bent.

![reference, flat dress, result](docs/result.jpg)

## Run it

```bash
cd /c/Projects/stocksnap/experiments/dress-swap
python swap.py ref_blue.png dress.jpg out.png swap.json
```
(needs `opencv-python` and `numpy`, already installed with StockSnap's backend).
For many dresses: loop over the dress photos with the same reference and settings.

## Settings (`swap.json`), set once per reference photo, in its pixels

- `skirt.waist_centre` / `waist_radii`, `hem_centre` / `hem_radii`: the skirt's
  waist and hem as ellipses in the reference.
- `bodice.quad`: four corners of the old top (top-left, top-right, bottom-right,
  bottom-left). `old_top_hue`: the old top's colour (OpenCV hue; blue = 100-135).
- `old_dress_outline`: polygon round the whole old dress.
- `keep_on_top`: outlines of the arms, hand with ball and hair.
- `dress_photo.bodice_box`: the bodice in the flat dress photo `[left, top, right, bottom]`.

## Limits

- The reference's own neckline and armhole trims (silver here) stay; they come
  from the reference, not from the new dress.
- The new dress should be the same cut as the one in the reference.
- Near the waist the skirt pattern is stretched a little.
