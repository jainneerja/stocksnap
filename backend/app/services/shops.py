"""Shops: separate inventories on one laptop (e.g. a clothing brand and a
jewellery line).

Each shop is its own folder - database, photos and settings - so data can
never mix, and a shop can be backed up or moved by copying one folder:

    <data_dir>/shops/<slug>/
        shop.json        name, type, SKU prefix, low-stock default, logo
        stocksnap.db
        images/
        logo.png         (optional)

Shops organise data; they are not a security boundary (no passwords).
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..config import Settings

SHOP_KINDS = ("clothing", "jewellery", "soap", "candle", "other")


class ShopInfo(BaseModel):
    slug: str
    name: str = Field(min_length=1, max_length=80)
    kind: str = "other"  # one of SHOP_KINDS; picks default categories / bulk type
    sku_prefix: str = ""  # e.g. "SIB" -> SIB-00012; empty = category based (TSH-00012)
    low_stock_default: int = Field(default=2, ge=0)
    ai_context: str = Field(default="", max_length=400)  # "what do you sell?", given to the AI
    # Item descriptions: instant (no AI) | fast (AI answers short facts) | full (AI writes freely)
    describe_mode: str = "fast"
    name_template: str = Field(default="", max_length=200)  # empty = default for the shop type
    desc_template: str = Field(default="", max_length=600)
    has_logo: bool = False
    created_at: str = ""


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "shop"


def suggest_prefix(name: str) -> str:
    """'Sora in Bloom' -> 'SIB', 'Lumière' -> 'LUM'."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) >= 2:
        p = "".join(w[0] for w in words)[:4]
    else:
        p = (words[0] if words else "SHOP")[:3]
    return p.upper()


def clean_prefix(prefix: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", prefix or "").upper()[:6]


@dataclass
class ShopContext:
    info: ShopInfo
    settings: Settings  # data_dir points at the shop folder
    engine: object


class ShopRegistry:
    def __init__(self, settings: Settings):
        self.base = settings
        self.root = settings.data_dir / "shops"
        self.root.mkdir(parents=True, exist_ok=True)
        self._engines: dict[str, object] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ storage

    def _dir(self, slug: str) -> Path:
        return self.root / slug

    def _write(self, info: ShopInfo) -> None:
        d = self._dir(info.slug)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "shop.json.tmp"
        tmp.write_text(json.dumps(info.model_dump(), indent=2), encoding="utf-8")
        os.replace(tmp, d / "shop.json")  # atomic: never a half-written file

    def get(self, slug: Optional[str]) -> Optional[ShopInfo]:
        if not slug or not re.fullmatch(r"[a-z0-9-]+", slug):
            return None
        f = self._dir(slug) / "shop.json"
        if not f.is_file():
            return None
        try:
            return ShopInfo(**json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a broken file shouldn't take the app down
            return None

    def list(self) -> list[ShopInfo]:
        shops = [s for s in (self.get(p.name) for p in self.root.iterdir() if p.is_dir()) if s]
        return sorted(shops, key=lambda s: (s.created_at, s.name))

    # ------------------------------------------------------------ changes

    def create(self, name: str, kind: str = "other", sku_prefix: Optional[str] = None,
               low_stock_default: int = 2, ai_context: str = "", describe_mode: str = "fast") -> ShopInfo:
        base = slugify(name)
        slug, n = base, 2
        with self._lock:
            while self._dir(slug).exists():
                slug, n = f"{base}-{n}", n + 1
            info = ShopInfo(
                slug=slug,
                name=name.strip(),
                kind=kind if kind in SHOP_KINDS else "other",
                sku_prefix=clean_prefix(suggest_prefix(name) if sku_prefix is None else sku_prefix),
                low_stock_default=low_stock_default,
                ai_context=(ai_context or "").strip()[:400],
                describe_mode=describe_mode if describe_mode in ("instant", "fast", "full") else "fast",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._write(info)
        return info

    def update(self, slug: str, **changes) -> ShopInfo:
        info = self.get(slug)
        if info is None:
            raise KeyError(slug)
        if "sku_prefix" in changes and changes["sku_prefix"] is not None:
            changes["sku_prefix"] = clean_prefix(changes["sku_prefix"])
        if changes.get("describe_mode") and changes["describe_mode"] not in ("instant", "fast", "full"):
            changes["describe_mode"] = "fast"
        if changes.get("kind") and changes["kind"] not in SHOP_KINDS:
            changes["kind"] = "other"
        data = info.model_dump() | {k: v for k, v in changes.items() if v is not None}
        info = ShopInfo(**data)
        self._write(info)
        return info

    @staticmethod
    def style(info: ShopInfo):
        from .listing import ShopStyle

        return ShopStyle(name=info.name, kind=info.kind, name_template=info.name_template,
                         desc_template=info.desc_template, mode=info.describe_mode)

    def logo_path(self, slug: str) -> Path:
        return self._dir(slug) / "logo.png"

    # ------------------------------------------------------------ runtime

    def context(self, info: ShopInfo) -> ShopContext:
        from ..db import make_engine

        settings = dataclasses.replace(self.base, data_dir=self._dir(info.slug))
        with self._lock:
            engine = self._engines.get(info.slug)
            if engine is None:
                engine = self._engines[info.slug] = make_engine(settings)
        return ShopContext(info=info, settings=settings, engine=engine)
