#!/usr/bin/env bash
# Wire the demo upload API: Fly app + GitHub deploy secrets + Vercel PUBLIC_API_BASE_URL.
set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-/Users/pranav_meraga/Downloads/yotta-robotics-demo}"
API_DIR="$DEMO_ROOT/api"
APP_NAME="${FLY_APP_NAME:-yotta-demo-api}"
ORG="${FLY_ORG:-}"
VERCEL_PROJECT="${VERCEL_PROJECT:-yotta-robotics-demo}"
GITHUB_REPO="${GITHUB_REPO:-pmeraga/yotta-robotics-demo}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

need flyctl
need gh
need vercel
need curl

echo "==> Checking Fly auth"
if ! flyctl auth whoami >/dev/null 2>&1; then
  echo "Opening Fly login…"
  flyctl auth login
fi
flyctl auth whoami

echo "==> Checking GitHub auth"
if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "Opening GitHub login (repo + workflow scopes needed for secrets)…"
  gh auth login -h github.com -p https -w
fi
gh auth status -h github.com

echo "==> Ensuring Fly app exists: $APP_NAME"
cd "$API_DIR"
if ! flyctl status -a "$APP_NAME" >/dev/null 2>&1; then
  if [[ -n "$ORG" ]]; then
    flyctl apps create "$APP_NAME" --org "$ORG"
  else
    flyctl apps create "$APP_NAME"
  fi
fi

echo "==> Creating Fly deploy token"
FLY_API_TOKEN="$(flyctl tokens create deploy -x 999999h -a "$APP_NAME" --name "yotta-demo-github-actions" 2>/dev/null \
  || flyctl tokens create org -x 999999h --name "yotta-demo-github-actions")"
if [[ -z "${FLY_API_TOKEN:-}" ]]; then
  echo "Could not create a Fly deploy token." >&2
  exit 1
fi

echo "==> Create a fine-grained GitHub PAT for private yotta-core:"
echo "  https://github.com/settings/personal-access-tokens/new"
echo "  Resource owner: pmeraga (your user)"
echo "  Repository access: Only select repositories → yotta-core"
echo "  Repository permissions:"
echo "    Contents → Read-only"
echo "    Metadata → Read-only (required)"
echo "  Do NOT choose 'Public repositories (read-only)' — that excludes private yotta-core."
open "https://github.com/settings/personal-access-tokens/new" 2>/dev/null || true
read -r -s -p "Paste YOTTA_CORE_TOKEN: " YOTTA_CORE_TOKEN
echo
YOTTA_CORE_TOKEN="$(printf '%s' "$YOTTA_CORE_TOKEN" | tr -d '\n\r')"
[[ -n "${YOTTA_CORE_TOKEN:-}" ]] || { echo "YOTTA_CORE_TOKEN is required." >&2; exit 1; }

echo "==> Validating token can read pmeraga/yotta-core"
HTTP_CODE="$(curl -sS -o /tmp/yotta-core-token-check.json -w '%{http_code}' \
  -H "Authorization: Bearer ${YOTTA_CORE_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/pmeraga/yotta-core)"
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "Token check failed (HTTP $HTTP_CODE). Body:" >&2
  cat /tmp/yotta-core-token-check.json >&2 || true
  echo >&2
  echo "Fix the PAT permissions (Contents + Metadata Read on private yotta-core), then re-run." >&2
  exit 1
fi
echo "Token OK — repo is readable."

echo "==> Setting GitHub Actions secrets on $GITHUB_REPO"
gh secret set FLY_API_TOKEN -R "$GITHUB_REPO" --body "$FLY_API_TOKEN"
gh secret set YOTTA_CORE_TOKEN -R "$GITHUB_REPO" --body "$YOTTA_CORE_TOKEN"

echo "==> Deploying API to Fly"
flyctl deploy --remote-only \
  --app "$APP_NAME" \
  --build-secret "yotta_core_token=${YOTTA_CORE_TOKEN}"

API_URL="https://${APP_NAME}.fly.dev"
echo "==> Waiting for health: $API_URL/api/health"
for _ in $(seq 1 30); do
  curl -fsS "$API_URL/api/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "$API_URL/api/health"
echo

echo "==> Setting Vercel PUBLIC_API_BASE_URL=$API_URL"
cd "$DEMO_ROOT"
for ENV in production preview development; do
  vercel env rm PUBLIC_API_BASE_URL "$ENV" --yes >/dev/null 2>&1 || true
  printf '%s' "$API_URL" | vercel env add PUBLIC_API_BASE_URL "$ENV"
done

echo "==> Redeploying Vercel production"
vercel --prod --yes

echo
echo "Done."
echo "  API:  $API_URL"
echo "  Site: https://yotta-robotics-demo.vercel.app"
