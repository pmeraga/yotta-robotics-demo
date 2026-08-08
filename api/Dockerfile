# syntax=docker/dockerfile:1.7

# Two stages on purpose: the token and git only exist in the builder, so neither the
# credential nor the pipeline's git history can survive into a published image layer.
FROM python:3.11-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# Clone with the mounted token, then install from a local path so pip never prints
# ``git+https://…token…`` in build logs. Fine-grained PATs authenticate as
# ``x-access-token``; strip CR/LF in case the secret was pasted with a newline.
RUN --mount=type=secret,id=yotta_core_token \
    set -eu; \
    TOKEN="$(tr -d '\n\r' < /run/secrets/yotta_core_token)"; \
    test -n "$TOKEN"; \
    git -c advice.detachedHead=false clone --depth 1 \
      "https://x-access-token:${TOKEN}@github.com/pmeraga/yotta-core.git" \
      /tmp/yotta-core; \
    pip install "/tmp/yotta-core[demo]"; \
    rm -rf /tmp/yotta-core


FROM python:3.11-slim

RUN useradd --create-home --uid 10001 yotta
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JOB_ROOT=/tmp/yotta

WORKDIR /app
COPY main.py .

USER yotta
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health').read()"

# One worker: each job is CPU-bound video work, and concurrency is bounded per client
# in the application rather than by forking more processes than the machine has cores.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
