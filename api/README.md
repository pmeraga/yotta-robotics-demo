# Demo API

A thin FastAPI service. It handles uploads, job lifecycle, and file serving, and makes
exactly one call into the pipeline.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness plus the current upload limits |
| `POST` | `/api/jobs` | Accept a clip, validate it, queue processing |
| `GET` | `/api/jobs/{id}` | Status, current step, coarse progress |
| `GET` | `/api/jobs/{id}/result` | Summary plus video URLs |
| `GET` | `/api/jobs/{id}/video/{name}` | Stream `original`, `curated`, or `annotated` |

## Limits

Configured by environment variable, with hosted defaults:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | 52428800 | 50 MB upload cap |
| `MAX_FRAMES` | 1200 | Frame ceiling |
| `MAX_DURATION_SEC` | 45 | Duration ceiling |
| `MAX_ACTIVE_JOBS` | 3 | Concurrent jobs per client address |
| `JOB_TTL_SEC` | 3600 | Jobs and their files are deleted after this |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS allowlist |
| `JOB_ROOT` | system temp | Where job working directories live |

## Running locally

The pipeline package is private. With access to it:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install "yotta-core[demo] @ git+https://github.com/pmeraga/yotta-core.git"
uvicorn main:app --reload --port 8000
```

Without access, the frontend still builds and the published results still render; only
the live upload path needs the package.
