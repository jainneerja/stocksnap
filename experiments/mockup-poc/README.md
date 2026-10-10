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

## Run it, step by step (Windows, Git Bash)

**1. One-time setup** - you need the StockSnap backend environment (it has OpenCV and NumPy).
If you haven't set it up yet:

```bash
cd /c/Projects/stocksnap/backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

Optional, for better cut-outs on busy backgrounds (downloads a ~180 MB model on first use):

```bash
python -m pip install "rembg[cpu]"
```

**2. Go to the experiment folder and activate the environment**

```bash
cd /c/Projects/stocksnap/experiments/mockup-poc
source ../../backend/.venv/Scripts/activate
```

**3. Add the scene image** - photos are not in the repo. Copy the idol scene into the
template folder and name it `scene.png`:

```bash
cp /c/Projects/ai-edit-test/pink_final.png templates/gopal1/scene.png
```

`templates/gopal1/template.json` holds pixel positions for **this exact image (1122 × 1402)**.
A different scene image needs its own template (see *Making a new template* below).

**4. Add a dress photo** - a flat, round dress shot from straight above, top piece up,
on a plain dark or light cloth:

```bash
cp /c/Projects/ai-edit-test/dress.jpg dress.jpg
```

**5. Make the mockup**

```bash
python mockup.py templates/gopal1 dress.jpg out/dress_on_gopal1.png --debug
```

It prints something like `{'seconds': 1.2, ...}` and saves:

| File | What it is |
|---|---|
| `out/dress_on_gopal1.png` | the result: your real dress on the idol |
| `out/dress_on_gopal1_layers.png` | check view: green = idol kept on top, blue = old dress removed, yellow = where the skirt is laid, red = where the top piece goes |
| `out/dress_on_gopal1_cutout.png` | the cut-out dress |

**6. Try more dresses** - same command, different photo and output name:

```bash
python mockup.py templates/gopal1 blue_dress.jpg out/blue_on_gopal1.png
```

**If something goes wrong**

- *Slow first run, or an error about downloading a model:* rembg is fetching its model.
  Skip it for dresses on plain cloth: `MOCKUP_NO_REMBG=1 python mockup.py templates/gopal1 dress.jpg out/test.png`
- *"Couldn't read the template scene or the dress photo":* check the file names
  (`dress.jpg` vs `dress.jpeg`) and that `templates/gopal1/scene.png` exists.
- *`python: command not found` or missing `cv2`:* activate the environment again (step 2).
- *Parts of the old dress or a cut-off arm in the result:* the scene isn't the one the
  template was made for - see below.

**Easier for other scenes:** in the StockSnap app, *Photos -> Your scenes* does the same
thing for any image with an oval, a box and a brush instead of coordinates.

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
