"""Public API for the Yotta curation demo.

This service owns uploads, job lifecycle, and file serving. It contains no curation
logic: the entire pipeline surface is the single ``run_demo_pipeline`` call in
:func:`_process`, which returns a result that has already been sanitized upstream.

Job metadata is mirrored to disk under each job's work dir so a process restart
(or a health-check flap) does not immediately lose in-flight uploads.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from yotta_mcap.demo import run_demo_pipeline

logger = logging.getLogger("yotta.demo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
MAX_FRAMES = int(os.getenv("MAX_FRAMES", 1200))
MAX_DURATION_SEC = float(os.getenv("MAX_DURATION_SEC", 45))
JOB_TTL_SEC = float(os.getenv("JOB_TTL_SEC", 3600))
MAX_ACTIVE_JOBS = int(os.getenv("MAX_ACTIVE_JOBS", 3))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

JOB_ROOT = Path(os.getenv("JOB_ROOT", tempfile.gettempdir())) / "yotta-demo-jobs"
JOB_ROOT.mkdir(parents=True, exist_ok=True)

Status = Literal["queued", "running", "done", "error"]

STEPS = [
    "Reading video",
    "Checking lighting and temporal quality",
    "Detecting failure and recovery structure",
    "Proposing corrected phase labels",
    "Curating frames",
    "Rendering video",
    "Done",
]


@dataclass
class Job:
    id: str
    work_dir: Path
    client: str
    status: Status = "queued"
    step: str = "Queued"
    progress: float = 0.0
    created_at: float = field(default_factory=time.time)
    summary: dict[str, Any] | None = None
    error: str | None = None
    videos: dict[str, Path] = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()

app = FastAPI(title="Yotta curation demo", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _status_path(work_dir: Path) -> Path:
    return work_dir / "status.json"


def _persist(job: Job) -> None:
    payload = {
        "id": job.id,
        "client": job.client,
        "status": job.status,
        "step": job.step,
        "progress": job.progress,
        "created_at": job.created_at,
        "summary": job.summary,
        "error": job.error,
        "videos": {name: path.as_posix() for name, path in job.videos.items()},
    }
    path = _status_path(job.work_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _load_job(job_id: str) -> Job | None:
    work_dir = JOB_ROOT / job_id
    path = _status_path(work_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    videos = {}
    for name, value in (payload.get("videos") or {}).items():
        video_path = Path(value)
        if video_path.exists():
            videos[name] = video_path
    return Job(
        id=str(payload.get("id", job_id)),
        work_dir=work_dir,
        client=str(payload.get("client", "unknown")),
        status=payload.get("status", "error"),  # type: ignore[arg-type]
        step=str(payload.get("step", "Unknown")),
        progress=float(payload.get("progress", 0.0)),
        created_at=float(payload.get("created_at", 0.0)),
        summary=payload.get("summary"),
        error=payload.get("error"),
        videos=videos,
    )


def _reap_expired() -> None:
    cutoff = time.time() - JOB_TTL_SEC
    with _lock:
        expired = [job for job in _jobs.values() if job.created_at < cutoff]
        for job in expired:
            _jobs.pop(job.id, None)
    # Also reap orphaned on-disk jobs the process no longer holds.
    if JOB_ROOT.exists():
        for child in JOB_ROOT.iterdir():
            if not child.is_dir():
                continue
            status = _status_path(child)
            created = None
            if status.exists():
                try:
                    created = float(json.loads(status.read_text(encoding="utf-8")).get("created_at", 0))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    created = None
            if created is None:
                created = child.stat().st_mtime
            if created < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                with _lock:
                    _jobs.pop(child.name, None)
    for job in expired:
        shutil.rmtree(job.work_dir, ignore_errors=True)


def _active_for(client: str) -> int:
    with _lock:
        return sum(1 for j in _jobs.values() if j.client == client and j.status in ("queued", "running"))


def _set(job: Job, **fields: Any) -> None:
    with _lock:
        for key, value in fields.items():
            setattr(job, key, value)
        _persist(job)


def _process(job: Job, video_path: Path) -> None:
    def on_progress(message: str) -> None:
        index = STEPS.index(message) if message in STEPS else 0
        _set(job, step=message, progress=round(index / (len(STEPS) - 1), 2))

    _set(job, status="running", step=STEPS[0], progress=0.0)
    try:
        import inspect

        kwargs: dict[str, Any] = {"progress": on_progress}
        params = inspect.signature(run_demo_pipeline).parameters
        if "annotate_max_width" in params:
            kwargs["annotate_max_width"] = 640
        if "annotate_frame_stride" in params:
            kwargs["annotate_frame_stride"] = 2
        result = run_demo_pipeline(video_path, job.work_dir / "run", **kwargs)
        _set(
            job,
            status="done",
            step="Done",
            progress=1.0,
            summary=result.summary,
            videos={
                "original": result.original_video,
                "curated": result.curated_video,
                "annotated": result.annotated_video,
            },
        )
        logger.info("job %s finished: %s frames kept", job.id, result.summary.get("kept_frames"))
    except Exception as exc:  # surfaced to the user as a generic message
        logger.exception("job %s failed", job.id)
        _set(job, status="error", error=str(exc)[:200] or "Processing failed.")


@app.get("/api/health")
def health() -> dict[str, Any]:
    # Cheap check only — do not reap on the hot path while a job is encoding.
    return {"status": "ok", "limits": {"max_mb": MAX_UPLOAD_BYTES // (1024 * 1024), "max_seconds": MAX_DURATION_SEC}}


@app.post("/api/jobs")
async def create_job(request: Request, background: BackgroundTasks, file: UploadFile = File(...)) -> JSONResponse:
    _reap_expired()

    client = _client_key(request)
    if _active_for(client) >= MAX_ACTIVE_JOBS:
        raise HTTPException(429, "You already have a clip processing. Please wait for it to finish.")

    filename = (file.filename or "").lower()
    if not filename.endswith((".mp4", ".mov", ".m4v")):
        raise HTTPException(415, "Please upload an MP4 or MOV video.")

    job_id = uuid.uuid4().hex[:12]
    work_dir = JOB_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    upload_path = work_dir / "upload.mp4"

    written = 0
    try:
        with upload_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"Video is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
                handle.write(chunk)
    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    if written == 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(400, "The uploaded file was empty.")

    # Probe before queueing so an oversized clip fails immediately rather than after
    # occupying a worker slot.
    try:
        from yotta_mcap.demo import probe_video

        probed = probe_video(upload_path)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(400, "That file could not be read as a video.")

    if probed.frames > MAX_FRAMES or probed.duration_sec > MAX_DURATION_SEC:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            413,
            f"Clip is {probed.duration_sec:.0f}s. The hosted demo accepts up to "
            f"{MAX_DURATION_SEC:.0f}s ({MAX_FRAMES} frames).",
        )

    job = Job(id=job_id, work_dir=work_dir, client=client)
    with _lock:
        _jobs[job_id] = job
        _persist(job)

    background.add_task(_process, job, upload_path)
    logger.info("job %s queued: %s frames, %.1fs", job_id, probed.frames, probed.duration_sec)

    return JSONResponse(
        {"id": job_id, "status": job.status, "frames": probed.frames, "duration_sec": round(probed.duration_sec, 1)},
        status_code=202,
    )


def _require(job_id: str) -> Job:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            return job
    loaded = _load_job(job_id)
    if loaded is None:
        raise HTTPException(404, "That job has expired or does not exist.")
    # A process restart can leave a job stuck in running with no worker — surface that.
    if loaded.status in {"queued", "running"}:
        loaded.status = "error"
        loaded.error = (
            "Processing was interrupted on the server. Please upload the clip again."
        )
        _persist(loaded)
    with _lock:
        _jobs[job_id] = loaded
        return loaded


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = _require(job_id)
    return {"id": job.id, "status": job.status, "step": job.step, "progress": job.progress, "error": job.error}


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str) -> dict[str, Any]:
    job = _require(job_id)
    if job.status == "error":
        raise HTTPException(500, job.error or "Processing failed.")
    if job.status != "done":
        raise HTTPException(409, "This job is still running.")
    return {
        "id": job.id,
        "summary": job.summary,
        "video": {name: f"/api/jobs/{job.id}/video/{name}" for name in job.videos},
    }


@app.get("/api/jobs/{job_id}/video/{name}")
def job_video(job_id: str, name: str) -> FileResponse:
    job = _require(job_id)
    path = job.videos.get(name)
    if path is None or not path.exists():
        raise HTTPException(404, "That video is not available.")
    return FileResponse(path, media_type="video/mp4", filename=f"{name}_{job.id}.mp4")
