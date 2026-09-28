""""Which of my items is this?" - visual similarity search over your own catalogue.

Two interchangeable embedders:

* ClipEmbedder  - OpenCLIP ViT-B-32 (MIT licence, LAION weights). Robust to
  angle/lighting changes. Needs `pip install -r requirements-ai.txt`; weights
  (~350 MB) download once, then it runs fully offline.
* LiteEmbedder  - colour histogram + edge layout using only Pillow/numpy.
  Tiny and instant, but only reliable for photos taken in similar conditions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np
from PIL import Image, ImageFilter

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def embed(self, img: Image.Image) -> list[float]: ...


class LiteEmbedder:
    name = "lite-v1"

    def embed(self, img: Image.Image) -> list[float]:
        small = img.convert("RGB").resize((64, 64))
        # 1) colour: 4x4x4 RGB histogram (64 dims)
        arr = np.asarray(small, dtype=np.int32) // 64
        idx = arr[..., 0] * 16 + arr[..., 1] * 4 + arr[..., 2]
        hist = np.bincount(idx.ravel(), minlength=64).astype(np.float32)
        hist = np.sqrt(hist)  # soften dominant background colours
        # 2) layout: 8x8 edge-density grid (64 dims)
        edges = np.asarray(small.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
        grid = edges.reshape(8, 8, 8, 8).mean(axis=(1, 3)).ravel()
        vec = np.concatenate([hist / (np.linalg.norm(hist) or 1), grid / (np.linalg.norm(grid) or 1)])
        return _normalise(vec).tolist()


class ClipEmbedder:
    name = "openclip-vit-b-32"

    def __init__(self) -> None:
        import open_clip  # noqa: F401  (import error => not installed)
        import torch

        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        self._model.eval()

    def embed(self, img: Image.Image) -> list[float]:
        with self._torch.no_grad():
            tensor = self._preprocess(img.convert("RGB")).unsqueeze(0)
            vec = self._model.encode_image(tensor)[0].cpu().numpy()
        return _normalise(vec).tolist()


def _normalise(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def make_embedder(mode: str) -> Optional[Embedder]:
    if mode == "off":
        return None
    if mode in ("clip", "auto"):
        try:
            return ClipEmbedder()
        except Exception as exc:  # noqa: BLE001
            if mode == "clip":
                log.warning("CLIP unavailable (%s); falling back to lite matcher", exc)
            else:
                log.info("CLIP not installed; using lite matcher")
    return LiteEmbedder()


@dataclass
class Match:
    item_id: int
    score: float


def rank(query: list[float], candidates: list[tuple[int, str]], top_k: int = 5) -> list[Match]:
    """candidates: (item_id, embedding_json). Returns best matches first."""
    if not candidates:
        return []
    ids = [c[0] for c in candidates]
    mat = np.array([json.loads(c[1]) for c in candidates], dtype=np.float32)
    scores = mat @ np.asarray(query, dtype=np.float32)
    order = np.argsort(-scores)[:top_k]
    return [Match(item_id=ids[i], score=round(float(scores[i]), 4)) for i in order]
