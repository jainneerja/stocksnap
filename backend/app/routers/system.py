from __future__ import annotations

import io
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..db import current_shop, shop_settings
from ..services import barcode

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(request: Request):
    ai = request.app.state.ai
    return {
        "status": "ok",
        "version": __version__,
        "barcode": {"available": barcode.AVAILABLE},
        "vision": ai.vision.status(),
        "matcher": {
            "available": ai.embedder is not None,
            "model": getattr(ai.embedder, "name", None),
        },
    }


@router.get("/backup")
def backup(request: Request):
    """Zip of the database (consistent snapshot) plus all item photos."""
    settings = shop_settings(request)
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "stocksnap.db"
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, "stocksnap.db")
            for img in settings.images_dir.glob("*.jpg"):
                zf.write(img, f"images/{img.name}")
            for extra in ("shop.json", "logo.png"):
                if (settings.data_dir / extra).is_file():
                    zf.write(settings.data_dir / extra, extra)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=stocksnap-{current_shop(request).info.slug}-backup-{stamp}.zip"},
    )
