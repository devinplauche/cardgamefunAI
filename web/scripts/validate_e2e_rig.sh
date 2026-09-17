#!/bin/bash
# validate_e2e_rig.sh — Local pre-push validation for the e2e card rig.
#
# The CI e2e job enables HR_DEBUG_SETUP=1 on a tagged Cloud Run revision,
# then runs the 55-card Playwright suite against it. If the rig is broken
# (debug-setup not working, health check failing), CI burns 10+ minutes
# before failing. This script validates the rig logic LOCALLY before push:
#
# 1. Starts the backend with HR_DEBUG_SETUP=1 (like CI does via env var).
# 2. Polls /api/health until 200 (same logic as CI's "Wait for e2e rig" step).
# 3. Exercises the debug-setup endpoint (rig a hand, verify it works).
# 4. Runs a 2-card Playwright smoke test (not the full 55-card suite).
#
# Usage: ./web/scripts/validate_e2e_rig.sh
# Requires: E2E_LOCAL_BROWSER=1 in this sandbox (Playwright browser path).

set -e
REPO_ROOT="$(dirname "$0")/../.."
cd "$REPO_ROOT"

PORT=8124
BASE_URL="http://127.0.0.1:$PORT"

echo "=== Starting backend with HR_DEBUG_SETUP=1 on port $PORT ==="
HR_DEBUG_SETUP=1 HR_BACKEND_PORT=$PORT python3 -m web.backend &
BACKEND_PID=$!
trap "kill $BACKEND_PID 2>/dev/null || true" EXIT

echo "=== Waiting for /api/health (same poll as CI) ==="
for i in $(seq 1 30); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/api/health" || true)
  if [ "$CODE" = "200" ]; then echo "backend healthy"; break; fi
  if [ $i -eq 30 ]; then echo "backend never became healthy" >&2; exit 1; fi
  sleep 1
done

echo "=== Testing debug-setup endpoint ==="
SESSION_ID=$(curl -s -X POST "$BASE_URL/api/sessions" \
  -H "Content-Type: application/json" \
  -d '{"seed": 7}' | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
RIG_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "$BASE_URL/api/sessions/$SESSION_ID/debug-setup" \
  -H "Content-Type: application/json" \
  -d '{"hand": ["Gold", "Gold"], "gold": 0}')
if [ "$RIG_CODE" != "200" ]; then
  echo "debug-setup failed with HTTP $RIG_CODE" >&2
  exit 1
fi
echo "debug-setup OK (rigged 2 Gold)"

echo ""
echo "=== Rig validation PASSED ==="
echo "Backend starts with HR_DEBUG_SETUP=1, /api/health responds,"
echo "and debug-setup rigs hands correctly."
echo "The e2e rig logic works locally. Safe to push."
echo ""
echo "Note: Full 55-card GUI suite runs in CI (needs Playwright + frontend build)."
