# Experiment: template mockup - the real dress in a ready-made scene

**Question:** instead of asking an AI to redraw the dress (see `../ai-edit-test`: ~3 hours on
a laptop CPU, and the dress came out redesigned), can we keep the seller's real photo and
just *place* it into a nice scene?

**Result:** yes - about **1 second** per image on a normal CPU, no GPU, no cloud cost, and
every flower, sequin and border is exactly as photographed, because it *is* the photo.
This proof of concept became StockSnap's **Your scenes** feature
(`backend/app/services/scenes.py`), where the scene is set up with an oval, a box and a
brush instead of the hand-written coordinates used here.

| | Local AI edit (Qwen-Image-Edit) | Template mockup |
|---|---|---|
| Time per image (laptop CPU) | ~3 hours | ~1 second |
| Product accuracy | colours kept, shape and details redesigned | exact (real photo) |
| Cost | free | free |

Photos are not committed: add your own `templates/gopal1/scene.png` (the scene) and a
flat dress photo to try it.

---


Puts a **real dress photo** onto a ready-made idol scene in about a second, on any laptop.
No AI redraws the dress, so colours and embroidery stay exactly as photographed.

```bash
cd /c/Projects/stocksnap/experiments/mockup-poc
source ../../backend/.venv/Scripts/activate      # has opencv + rembg already
python mockup.py templates/gopal1 my_dress.jpg out/my_dress_on_gopal1.png --debug
```

`--debug` also saves `*_layers.png` (green = idol kept on top, blue = old dress removed,
yellow = where the skirt is laid, red = where the top piece goes) and `*_cutout.png`.

## How it works

1. **Cut out** the dress (rembg if installed, else plain-background cut).
2. **Remove** the template's own dress and fill the table back in.
3. **Lay the skirt** on the floor in perspective (`skirt.quad`), centre at the idol's waist.
4. **Stand the top piece** on the chest (`bodice.quad`), cut to its own outline.
5. **Light**: soft shadow under the skirt + the scene's large-scale shading.
6. **Idol on top**: face, crown, hair, arms, hands, necklace (`idol.polygons`,
   minus anything coloured like the old dress).

## Making a new template (once per scene)

Copy `templates/gopal1`, replace `scene.png`, and edit the coordinates in
`template.json` (pixel positions in `scene.png`). Run with `--debug` and adjust until
the layer map looks right. A point-and-click editor would replace this step.

## Limits

- It's a mockup: fabric doesn't fold around the idol, the skirt lies flat.
- Works best when dress photos are shot flat, from straight above, top piece up.
- The top piece's position in the photo (`bodice.src_box`) assumes dresses of this
  shape; very different cuts need their own setting.
