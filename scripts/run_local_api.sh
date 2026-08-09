#!/usr/bin/env bash
# Run the demo upload API on this Mac (same path as the offline site assets).
#
# Usage:
#   bash scripts/run_local_api.sh
#
# Then either:
#   - point PUBLIC_API_BASE_URL at http://127.0.0.1:8080 for local web testing, or
#   - expose it with Cloudflare Tunnel / ngrok and set that URL on Vercel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="${YOTTA_CORE_PATH:-/Users/pranav_meraga/Downloads/yotta-core}"
PORT="${PORT:-8080}"

export PYTHONPATH="${CORE}/src:${PYTHONPATH:-}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:4321,https://yotta-robotics-demo.vercel.app}"
export JOB_ROOT="${JOB_ROOT:-/tmp/yotta-local-demo}"
export MAX_UPLOAD_BYTES="${MAX_UPLOAD_BYTES:-52428800}"
export MAX_DURATION_SEC="${MAX_DURATION_SEC:-45}"

cd "$ROOT/api"
python3 -m pip install -q -r requirements.txt "av>=12" pillow pyarrow
python3 -m pip install -q -e "${CORE}[demo]"

echo "API listening on http://127.0.0.1:${PORT}"
echo "Health: http://127.0.0.1:${PORT}/api/health"
exec python3 -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --workers 1
