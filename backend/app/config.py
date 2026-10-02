"""Runtime settings. Everything is read from environment variables so the app
works out of the box with no config file, and power users can tweak it."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    return Path(os.environ.get("STOCKSNAP_DATA_DIR", Path.home() / ".stocksnap"))


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)

    # Local LLM via Ollama (https://ollama.com). Nothing leaves the machine.
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_URL", "http://localhost:11434")
    )
    vision_model: str = field(
        default_factory=lambda: os.environ.get("STOCKSNAP_VISION_MODEL", "qwen2.5vl:3b")
    )
    vision_timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("STOCKSNAP_VISION_TIMEOUT", "300"))
    )

    # "auto" = CLIP if installed, else the lightweight colour-histogram matcher.
    # "clip" | "lite" | "off"
    matcher: str = field(default_factory=lambda: os.environ.get("STOCKSNAP_MATCHER", "auto"))
    match_threshold: float = field(
        default_factory=lambda: float(os.environ.get("STOCKSNAP_MATCH_THRESHOLD", "0.80"))
    )

    max_image_px: int = 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "stocksnap.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    def ensure_dirs(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
