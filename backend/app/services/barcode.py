"""Offline barcode reading with zxing-cpp (Apache-2.0).

Supports UPC-A/E, EAN-8/13, Code 128/39/93, QR, DataMatrix, PDF417 and more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image

try:
    import zxingcpp

    AVAILABLE = True
except ImportError:  # pragma: no cover
    zxingcpp = None
    AVAILABLE = False


@dataclass
class BarcodeHit:
    text: str
    format: str


def read_barcode(img: Image.Image) -> Optional[BarcodeHit]:
    if not AVAILABLE:
        return None
    results = zxingcpp.read_barcodes(img)
    if not results:
        # Retry on a grayscale, larger copy - helps with small/blurry codes.
        gray = img.convert("L")
        if max(gray.size) < 1600:
            scale = 1600 / max(gray.size)
            gray = gray.resize((int(gray.width * scale), int(gray.height * scale)))
        results = zxingcpp.read_barcodes(gray)
    for r in results:
        if r.text:
            return BarcodeHit(text=r.text.strip(), format=str(r.format).split(".")[-1])
    return None
