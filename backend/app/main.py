"""StockSnap API.

Run for development:   uvicorn app.main:app --reload
Run for phone access:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .db import make_engine
from .routers import batches, items, reports, sales, scan, system
from .services.ai import AI

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(settings: Optional[Settings] = None, ai: Optional[AI] = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="StockSnap", version=__version__)
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.ai = ai or AI.from_settings(settings)

    # Dev server (Vite on :5173) talks to the API on :8000.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for r in (items, scan, batches, sales, reports, system):
        app.include_router(r.router)

    app.mount("/images", StaticFiles(directory=settings.images_dir), name="images")

    # Serve the built React app, so a single `uvicorn` command runs everything.
    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            file = (FRONTEND_DIST / path).resolve()
            if path and file.is_file() and FRONTEND_DIST in file.parents:
                return FileResponse(file)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
