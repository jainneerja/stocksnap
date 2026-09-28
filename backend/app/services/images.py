from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps


class InvalidImage(ValueError):
    pass


def load_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # respect phone camera rotation
        return img.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise InvalidImage("Could not read that image. Try a JPG or PNG.") from exc


def save_image(img: Image.Image, images_dir: Path, max_px: int) -> str:
    """Downscale and save as JPEG. Returns the file name (relative to images_dir)."""
    img = img.copy()
    img.thumbnail((max_px, max_px))
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(images_dir / name, "JPEG", quality=85)
    return name


def resolve_image(images_dir: Path, name: str) -> Path:
    """Resolve an image name safely (no path traversal)."""
    path = (images_dir / Path(name).name).resolve()
    if path.parent != images_dir.resolve() or not path.is_file():
        raise FileNotFoundError(name)
    return path
