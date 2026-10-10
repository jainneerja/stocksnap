"""Image lab (proof of concept): upload one product photo, get listing images."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from ..db import current_shop
from ..services.imagelab import LOOKS, SCENES, LabOptions, load_image_any

router = APIRouter(prefix="/api/lab", tags=["image lab"])

MAX_UPLOAD = 25 * 1024 * 1024


def _root(request: Request):
    root = current_shop(request).settings.data_dir / "lab"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job(request: Request, job_id: str) -> dict:
    try:
        return request.app.state.lab.read(_root(request), job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Job not found")


@router.get("/status")
def status(request: Request):
    return request.app.state.lab.status()


@router.post("/jobs", status_code=201)
async def create_job(
    request: Request,
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    looks: str = Form("main_white,shadow_grey,gradient,tabletop,closeup,card"),
    scene: str = Form("table"),
    custom_prompt: str = Form(""),
    ai_count: int = Form(2),
    title: str = Form(""),
    bullets: str = Form(""),
    scene_ids: str = Form(""),
):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is too large (max 25 MB)")
    try:
        img = load_image_any(data)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Could not read that image. Try a JPG or PNG.")
    chosen = [k for k in looks.split(",") if k in LOOKS]
    if not chosen:
        raise HTTPException(400, "Pick at least one look")
    if scene not in SCENES and scene != "custom":
        scene = "table"
    opts = LabOptions(
        looks=chosen, scene=scene, custom_prompt=custom_prompt[:300], ai_count=max(1, min(ai_count, 4)),
        title=title[:120], bullets=[b[:160] for b in bullets.splitlines() if b.strip()][:5],
        brand=current_shop(request).info.name,
        scene_ids=[s for s in scene_ids.split(",") if s][:6],
    )
    lab = request.app.state.lab
    root = _root(request)
    job = lab.create(root, img, opts)
    tasks.add_task(lab.run, root, job["id"])
    return job


@router.get("/jobs")
def list_jobs(request: Request):
    root = _root(request)
    jobs = []
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
        try:
            jobs.append(request.app.state.lab.read(root, d.name))
        except Exception:  # noqa: BLE001
            continue
    return jobs


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    return _job(request, job_id)


@router.get("/files/{job_id}/{name}", include_in_schema=False)
def job_file(job_id: str, name: str, request: Request):
    _job(request, job_id)
    d = request.app.state.lab.job_dir(_root(request), job_id)
    allowed = {"original.jpg", "cutout.png"}
    path = d / ("out" if name not in allowed else "") / name
    if "/" in name or "\\" in name or ".." in name or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


@router.get("/jobs/{job_id}/zip")
def job_zip(job_id: str, request: Request, prefix: Optional[str] = None):
    _job(request, job_id)
    shop = current_shop(request).info
    name = "".join(c for c in (prefix or f"{shop.sku_prefix or 'IMG'}-{job_id[:6]}") if c.isalnum() or c in "-_")
    data = request.app.state.lab.zip_bytes(_root(request), job_id, name)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={name}-images.zip"})


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request):
    import shutil

    _job(request, job_id)
    shutil.rmtree(request.app.state.lab.job_dir(_root(request), job_id), ignore_errors=True)
