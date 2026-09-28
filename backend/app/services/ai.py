"""Holds the AI components for the running app and makes them easy to swap
(e.g. with fakes in tests)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from PIL import Image
from sqlmodel import Session, select

from ..config import Settings
from ..models import Item
from .matcher import Embedder, Match, make_embedder, rank
from .vision import OllamaVision


@dataclass
class AI:
    vision: OllamaVision
    embedder: Optional[Embedder]
    match_threshold: float

    @classmethod
    def from_settings(cls, s: Settings) -> "AI":
        return cls(
            vision=OllamaVision(s.ollama_url, s.vision_model, s.vision_timeout_s),
            embedder=make_embedder(s.matcher),
            match_threshold=s.match_threshold,
        )

    def index_item(self, item: Item, img: Image.Image) -> None:
        if self.embedder is None:
            return
        item.embedding = json.dumps(self.embedder.embed(img))
        item.embedding_model = self.embedder.name

    def find_similar(self, session: Session, img: Image.Image, top_k: int = 5) -> list[Match]:
        if self.embedder is None:
            return []
        rows = session.exec(
            select(Item.id, Item.embedding).where(
                Item.embedding_model == self.embedder.name, Item.embedding.is_not(None)
            )
        ).all()
        matches = rank(self.embedder.embed(img), [(r[0], r[1]) for r in rows], top_k)
        return [m for m in matches if m.score >= self.match_threshold]
