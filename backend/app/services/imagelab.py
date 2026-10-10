"""Image lab (proof of concept): one product photo -> a set of listing images.

The rule that keeps listings honest: the PRODUCT is always the real photo.
Only the background, framing and text around it are generated.

    cut out the product  ->  place it on: white main image, soft shadow,
                             gradient, tabletop, AI-generated scene
                         ->  plus a detail close-up and a text details card

Engines (all open source, all local, all optional):
  * Cut-out: rembg (MIT) with the isnet-general-use model (~180 MB, ~1-2 s on CPU).
    Without rembg, an OpenCV GrabCut fallback works for photos on a plain background.
  * AI scenes: Hugging Face diffusers + SD-Turbo (generates the *background* only,
    512 px in 1-4 steps). Needs `pip install -r requirements-imagelab.txt`; the
    model (~2 GB) downloads once. Any diffusers text-to-image model can be set
    with STOCKSNAP_IMAGEGEN_MODEL. Check each model's licence before selling with it.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

log = logging.getLogger(__name__)

OUT = 2000  # marketplace-friendly square (Amazon zoom needs >= 1000 px)

LOOKS = {
    "main_white": "Main image (white)",
    "shadow_grey": "Soft shadow",
    "gradient": "Colour backdrop",
    "tabletop": "Tabletop",
    "closeup": "Close-up",
    "card": "Details card",
    "in_scene": "In your scenes",
    "ai_scene": "AI scene",
}

SCENES = {
    "table": "empty rustic wooden table top in front of a softly blurred cream wall, warm natural window light",
    "marble": "empty white marble surface, clean bright studio light, soft grey seamless background",
    "festive": "empty surface with soft golden fairy lights and scattered flower petals, warm festive glow, blurred",
    "nature": "empty light wooden surface, soft green leaves blurred in the background, fresh morning light",
    "silk": "empty surface draped with rich silk fabric in deep warm tones, soft elegant lighting",
}
SCENE_SUFFIX = (", empty space in the centre for a product, no people, no text, no logo, "
                "professional product photography background, shallow depth of field, high quality")


# ------------------------------------------------------------------ cut-out


class Cutter:
    """rembg if installed, else OpenCV GrabCut seeded from the plain-background detector."""

    def __init__(self, model: str):
        self.model = model
        self._session = None
        self._lock = threading.Lock()
        try:
            import rembg  # noqa: F401

            self.engine = "rembg"
        except Exception:  # noqa: BLE001
            self.engine = "basic"

    def status(self) -> dict:
        if self.engine == "rembg":
            return {"engine": "rembg", "model": self.model, "quality": "good"}
        return {"engine": "basic", "model": "OpenCV GrabCut", "quality": "plain backgrounds only",
                "hint": "pip install -r requirements-imagelab.txt for much better cut-outs"}

    def cut(self, img: Image.Image) -> Image.Image:
        mask = None
        if self.engine == "rembg":
            try:
                from rembg import new_session, remove

                with self._lock:
                    if self._session is None:
                        self._session = new_session(self.model)
                # rembg works at its own resolution; run on a ~1600 px copy and scale the mask back
                work = img.copy()
                work.thumbnail((1600, 1600))
                mask = remove(work, session=self._session, only_mask=True).convert("L")
                mask = mask.resize(img.size, Image.LANCZOS)
            except Exception as exc:  # noqa: BLE001 - e.g. the model can't be downloaded offline
                log.warning("rembg failed, using the basic cut-out: %s", exc)
                self.engine = "basic"
        if mask is None:
            mask = _grabcut_mask(img)
        out = img.convert("RGBA")
        out.putalpha(mask)
        return out


def _grabcut_mask(img: Image.Image) -> Image.Image:
    from .segment import find_pieces

    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    scale = min(1.0, 1000 / max(h, w))
    small = cv2.resize(rgb, (int(w * scale), int(h * scale))) if scale < 1 else rgb.copy()
    sh, sw = small.shape[:2]
    pieces = find_pieces(img).pieces
    if pieces:
        p = max(pieces, key=lambda p: p.w * p.h)
        rect = (int(p.x * scale), int(p.y * scale), max(2, int(p.w * scale)), max(2, int(p.h * scale)))
    else:
        rect = (int(sw * 0.05), int(sh * 0.05), int(sw * 0.9), int(sh * 0.9))
    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.GaussianBlur(m, (5, 5), 0)  # soft edge
    return Image.fromarray(m).resize((w, h), Image.LANCZOS)


# --------------------------------------------------------------- generator


class SceneGenerator:
    """Text-to-image for backgrounds via diffusers. Loaded lazily, once."""

    def __init__(self, model: str):
        self.model = model
        self._pipe = None
        self._lock = threading.Lock()
        self.error = ""
        try:
            import diffusers  # noqa: F401
            import torch  # noqa: F401

            self.installed = True
        except Exception:  # noqa: BLE001
            self.installed = False

    def device(self) -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return "mps"
        except Exception:  # noqa: BLE001
            pass
        return "cpu"

    def status(self) -> dict:
        if not self.installed:
            return {"available": False, "model": self.model,
                    "detail": "Not installed: pip install -r requirements-imagelab.txt"}
        return {"available": True, "model": self.model, "device": self.device(),
                "loaded": self._pipe is not None, "detail": self.error or "ready"}

    def _load(self):
        import torch
        from diffusers import AutoPipelineForText2Image

        dev = self.device()
        dtype = torch.float16 if dev == "cuda" else torch.float32
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(self.model, torch_dtype=dtype, variant="fp16")
        except Exception:  # noqa: BLE001 - some repos have no fp16 variant
            pipe = AutoPipelineForText2Image.from_pretrained(self.model, torch_dtype=dtype)
        pipe = pipe.to(dev)
        try:
            pipe.set_progress_bar_config(disable=True)
        except Exception:  # noqa: BLE001
            pass
        return pipe

    def generate(self, prompt: str, seed: int, steps: int = 2) -> Image.Image:
        import torch

        with self._lock:
            if self._pipe is None:
                self._pipe = self._load()
            g = torch.Generator(device="cpu").manual_seed(seed)
            kwargs = dict(prompt=prompt, num_inference_steps=steps, generator=g, height=512, width=512)
            if "turbo" in self.model.lower():
                kwargs["guidance_scale"] = 0.0  # turbo models are trained without CFG
            return self._pipe(**kwargs).images[0].convert("RGB")


# ----------------------------------------------------------------- compose


def _product_box(cut: Image.Image) -> tuple[int, int, int, int]:
    alpha = np.asarray(cut.split()[-1])
    ys, xs = np.where(alpha > 24)
    if len(xs) == 0:
        return (0, 0, cut.width, cut.height)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _fit(cut: Image.Image, fill: float, size: int = OUT) -> tuple[Image.Image, tuple[int, int]]:
    """Trim to the product, scale so its longest side is `fill` of the frame."""
    prod = cut.crop(_product_box(cut))
    s = fill * size / max(prod.size)
    prod = prod.resize((max(1, int(prod.width * s)), max(1, int(prod.height * s))), Image.LANCZOS)
    return prod, prod.size


def _shadow(prod: Image.Image, size: int, pos: tuple[int, int], strength: float = 0.35) -> Image.Image:
    """Soft contact shadow under the product."""
    layer = Image.new("L", (size, size), 0)
    w, h = prod.size
    x, y = pos
    d = ImageDraw.Draw(layer)
    d.ellipse((x + w * 0.08, y + h - h * 0.035, x + w * 0.92, y + h + h * 0.05), fill=int(255 * strength))
    layer = layer.filter(ImageFilter.GaussianBlur(size * 0.018))
    # a faint drop shadow from the product's own silhouette for depth
    sil = Image.new("L", (size, size), 0)
    sil.paste(prod.split()[-1].point(lambda a: int(a * strength * 0.5)), (x + int(w * 0.015), y + int(h * 0.02)))
    sil = sil.filter(ImageFilter.GaussianBlur(size * 0.012))
    return Image.fromarray(np.maximum(np.asarray(layer), np.asarray(sil)))


def compose(cut: Image.Image, background: Image.Image, fill: float = 0.85, shadow: float = 0.3,
            anchor: str = "center") -> Image.Image:
    bg = background.convert("RGB").resize((OUT, OUT), Image.LANCZOS)
    prod, (w, h) = _fit(cut, fill)
    x = (OUT - w) // 2
    y = (OUT - h) // 2 if anchor == "center" else int(OUT * 0.9) - h
    if shadow > 0:
        sh = _shadow(prod, OUT, (x, y), shadow)
        dark = Image.new("RGB", (OUT, OUT), (30, 25, 20))
        bg = Image.composite(dark, bg, sh)
    bg.paste(prod, (x, y), prod)
    return bg


def _solid(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (OUT, OUT), color)


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int], radial: bool = False) -> Image.Image:
    if radial:
        yy, xx = np.mgrid[0:OUT, 0:OUT].astype(np.float32)
        t = np.clip(np.hypot(xx - OUT / 2, yy - OUT * 0.45) / (OUT * 0.75), 0, 1)[..., None]
    else:
        t = np.linspace(0, 1, OUT, dtype=np.float32)[:, None, None].repeat(OUT, axis=1)
    arr = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    return Image.fromarray(arr.astype(np.uint8))


def dominant_color(cut: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(cut.convert("RGBA").resize((96, 96)))
    px = arr[arr[..., 3] > 128][:, :3].astype(np.float32)
    if len(px) == 0:
        return (200, 160, 120)
    # prefer saturated pixels (the "colour" of a dress), ignore near-white/black
    mx, mn = px.max(1), px.min(1)
    sat = (mx - mn) / np.maximum(mx, 1)
    pick = px[(sat > 0.25) & (mx > 60)]
    return tuple(int(v) for v in np.median(pick if len(pick) > 50 else px, axis=0))


def _pastel(c: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(v + (255 - v) * amount) for v in c)


def tabletop(base: tuple[int, int, int]) -> Image.Image:
    """Procedural 'wall + table' scene in the product's own colour family."""
    wall = _gradient(_pastel(base, 0.85), _pastel(base, 0.7), radial=True)
    table = _gradient(_pastel((176, 132, 92), 0.35), (150, 108, 72))
    img = wall.copy()
    horizon = int(OUT * 0.68)
    img.paste(table.crop((0, 0, OUT, OUT - horizon)).resize((OUT, OUT - horizon)), (0, horizon))
    edge = Image.new("L", (OUT, OUT), 0)
    ImageDraw.Draw(edge).rectangle((0, horizon - 6, OUT, horizon + 6), fill=90)
    img = Image.composite(Image.new("RGB", (OUT, OUT), (90, 70, 50)), img, edge.filter(ImageFilter.GaussianBlur(8)))
    return img.filter(ImageFilter.GaussianBlur(3))


def closeup(original: Image.Image, cut: Image.Image) -> tuple[Image.Image, str]:
    """Crop the busiest part of the product (embroidery, stones, print) from the
    ORIGINAL photo - real detail, not invented."""
    x0, y0, x1, y1 = _product_box(cut)
    gray = np.asarray(original.convert("L"), dtype=np.float32)
    alpha = np.asarray(cut.split()[-1]) > 64
    edges = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    edges *= alpha
    side = int(max(x1 - x0, y1 - y0) * 0.42)
    side = max(64, min(side, min(original.size)))
    integ = cv2.integral(edges)
    best, best_xy = -1.0, (x0, y0)
    step = max(8, side // 8)
    for y in range(max(0, y0), max(y0, y1 - side) + 1, step):
        for x in range(max(0, x0), max(x0, x1 - side) + 1, step):
            xe, ye = min(x + side, original.width), min(y + side, original.height)
            s = integ[ye, xe] - integ[y, xe] - integ[ye, x] + integ[y, x]
            if s > best:
                best, best_xy = s, (x, y)
    x, y = best_xy
    crop = original.crop((x, y, x + side, y + side)).convert("RGB")
    note = "" if side >= 700 else "Your photo is small for a close-up - a closer or higher-resolution photo will look sharper."
    return crop.resize((OUT, OUT), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 3)), note


def _font(size: int, bold: bool = False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf"] if bold
             else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf"])
    for n in names:
        for p in (n, f"/usr/share/fonts/truetype/dejavu/{n}", f"C:/Windows/Fonts/{n}", f"/Library/Fonts/{n}"):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def details_card(cut: Image.Image, title: str, bullets: list[str], brand: str) -> Image.Image:
    """Product on the left, title + bullet points on the right, brand at the bottom."""
    base = dominant_color(cut)
    bg = _gradient(_pastel(base, 0.92), _pastel(base, 0.8))
    prod, (w, h) = _fit(cut, 0.78)
    prod_scale = min(1.0, (OUT * 0.5) / w)
    if prod_scale < 1:
        prod = prod.resize((int(w * prod_scale), int(h * prod_scale)), Image.LANCZOS)
        w, h = prod.size
    x, y = int(OUT * 0.28) - w // 2, (OUT - h) // 2
    bg.paste(prod, (x, y), prod)
    d = ImageDraw.Draw(bg)
    ink = tuple(int(v * 0.35) for v in base)
    tx, tw = int(OUT * 0.56), int(OUT * 0.40)
    ty = int(OUT * 0.16)
    for line in _wrap(d, title or "Product details", _font(118, True), tw)[:3]:
        d.text((tx, ty), line, font=_font(118, True), fill=ink)
        ty += 138
    ty += 40
    d.rectangle((tx, ty, tx + 140, ty + 10), fill=ink)
    ty += 70
    for b in [b for b in bullets if b.strip()][:5]:
        lines = _wrap(d, b.strip(), _font(74), tw - 80)
        d.ellipse((tx, ty + 28, tx + 30, ty + 58), fill=ink)
        for i, line in enumerate(lines[:3]):
            d.text((tx + 68, ty), line, font=_font(74), fill=(40, 40, 40))
            ty += 90
        ty += 40
    if brand:
        d.text((tx, OUT - 200), brand.upper(), font=_font(64, True), fill=ink)
    return bg


# -------------------------------------------------------------------- jobs


@dataclass
class LabOptions:
    looks: list[str]
    scene: str = "table"
    custom_prompt: str = ""
    ai_count: int = 2
    title: str = ""
    bullets: Optional[list[str]] = None
    brand: str = ""
    scene_ids: Optional[list[str]] = None


class ImageLab:
    def __init__(self, cutout_model: str, imagegen_model: str):
        self.cutter = Cutter(cutout_model)
        self.generator = SceneGenerator(imagegen_model)

    def status(self) -> dict:
        return {"cutout": self.cutter.status(), "generator": self.generator.status(),
                "looks": LOOKS, "scenes": list(SCENES) + ["custom"]}

    # job files live in <shop>/lab/<job_id>/
    @staticmethod
    def job_dir(root: Path, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            raise FileNotFoundError(job_id)
        return root / job_id

    @staticmethod
    def read(root: Path, job_id: str) -> dict:
        d = ImageLab.job_dir(root, job_id)
        return json.loads((d / "job.json").read_text(encoding="utf-8"))

    @staticmethod
    def _write(d: Path, job: dict) -> None:
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
        os.replace(tmp, d / "job.json")

    def create(self, root: Path, original: Image.Image, opts: LabOptions) -> dict:
        job_id = uuid.uuid4().hex[:12]
        d = root / job_id
        (d / "out").mkdir(parents=True)
        img = original.copy()
        img.thumbnail((3000, 3000))
        img.save(d / "original.jpg", "JPEG", quality=92)
        job = {"id": job_id, "status": "queued", "message": "Waiting…", "created": time.time(),
               "options": opts.__dict__, "outputs": [], "notes": [], "total_s": 0}
        self._write(d, job)
        return job

    def run(self, root: Path, job_id: str) -> None:
        d = self.job_dir(root, job_id)
        job = self.read(root, job_id)
        o = LabOptions(**job["options"])
        start = time.time()

        def step(msg: str):
            job["status"], job["message"] = "running", msg
            self._write(d, job)

        def add(key: str, label: str, img: Image.Image, secs: float, extra: str = ""):
            name = f"{len(job['outputs']) + 1:02d}-{key}.jpg"
            img.convert("RGB").save(d / "out" / name, "JPEG", quality=90, optimize=True)
            job["outputs"].append({"file": name, "look": key, "label": label, "seconds": round(secs, 1),
                                   "note": extra, "kb": (d / "out" / name).stat().st_size // 1024})
            self._write(d, job)

        try:
            original = Image.open(d / "original.jpg").convert("RGB")
            step(f"Cutting out the product ({self.cutter.status()['engine']})…")
            t = time.time()
            cut = self.cutter.cut(original)
            cut.save(d / "cutout.png")
            job["cutout_s"] = round(time.time() - t, 1)
            box = _product_box(cut)
            if (box[2] - box[0]) * (box[3] - box[1]) < 0.02 * cut.width * cut.height:
                job["notes"].append("The cut-out looks very small - is the product clearly in the photo?")
            base = dominant_color(cut)

            for key in o.looks:
                t = time.time()
                if key == "main_white":
                    step("Main image on white…")
                    add(key, LOOKS[key], compose(cut, _solid((255, 255, 255)), 0.85, 0.18), time.time() - t + job["cutout_s"])
                elif key == "shadow_grey":
                    step("Soft shadow…")
                    add(key, LOOKS[key], compose(cut, _gradient((248, 248, 248), (226, 226, 228), True), 0.8, 0.45),
                        time.time() - t)
                elif key == "gradient":
                    step("Colour backdrop…")
                    add(key, LOOKS[key], compose(cut, _gradient(_pastel(base, 0.9), _pastel(base, 0.6), True), 0.8, 0.35),
                        time.time() - t)
                elif key == "tabletop":
                    step("Tabletop scene…")
                    add(key, LOOKS[key], compose(cut, tabletop(base), 0.72, 0.5, anchor="floor"), time.time() - t)
                elif key == "closeup":
                    step("Finding the most detailed area…")
                    img, note = closeup(original, cut)
                    add(key, LOOKS[key], img, time.time() - t, note)
                elif key == "card":
                    step("Details card…")
                    add(key, LOOKS[key], details_card(cut, o.title, o.bullets or [], o.brand), time.time() - t)
                elif key == "in_scene":
                    from .scenes import SceneStore

                    store = SceneStore(root.parent / "scenes")
                    for sid in o.scene_ids or []:
                        t = time.time()
                        try:
                            name = store.get(sid).name
                            step(f"Putting it in your scene '{name}'…")
                            add(key, name, store.render(sid, original, cut), time.time() - t)
                        except FileNotFoundError:
                            job["notes"].append("A chosen scene was deleted - skipped.")
                elif key == "ai_scene":
                    if not self.generator.installed:
                        job["notes"].append("AI scenes skipped: the image model isn't installed "
                                            "(pip install -r requirements-imagelab.txt).")
                        continue
                    prompt = (o.custom_prompt.strip() if o.scene == "custom" and o.custom_prompt.strip()
                              else SCENES.get(o.scene, SCENES["table"])) + SCENE_SUFFIX
                    for i in range(max(1, min(o.ai_count, 4))):
                        t = time.time()
                        first = self.generator._pipe is None
                        step(("Loading the AI image model (the very first time it also downloads ~2 GB)…" if first
                              else f"Painting AI scene {i + 1} of {o.ai_count}…"))
                        try:
                            bg = self.generator.generate(prompt, seed=1000 + i)
                        except Exception as exc:  # noqa: BLE001 - keep the other images
                            log.warning("AI scene failed: %s", exc)
                            self.generator.error = f"Couldn't run the AI model: {str(exc)[:160]}"
                            job["notes"].append(self.generator.error + " (The first run needs internet to download it.)")
                            break
                        bg = bg.resize((OUT, OUT), Image.LANCZOS).filter(ImageFilter.GaussianBlur(4))
                        add(key, f"{LOOKS[key]} {i + 1}", compose(cut, bg, 0.7, 0.45, anchor="floor"), time.time() - t,
                            "First run includes loading the model." if first else "")
            job["status"], job["message"] = "done", "Done"
        except Exception as exc:  # noqa: BLE001 - show the problem in the UI rather than hang
            log.exception("image lab job failed")
            job["status"], job["message"] = "failed", f"Something went wrong: {exc}"
        job["total_s"] = round(time.time() - start, 1)
        self._write(d, job)

    @staticmethod
    def zip_bytes(root: Path, job_id: str, prefix: str) -> bytes:
        d = ImageLab.job_dir(root, job_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, f in enumerate(sorted((d / "out").glob("*.jpg"))):
                slot = "MAIN" if i == 0 else f"PT{i:02d}"  # Amazon-style slot names
                zf.write(f, f"{prefix}.{slot}.jpg")
        return buf.getvalue()


def load_image_any(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(img).convert("RGB")
