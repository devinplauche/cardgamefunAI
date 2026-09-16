#!/usr/bin/env bash
# Deploy the Hero Realms multiplayer app to Cloud Run on the free tier.
#
# Prerequisites (one time):
#   1. gcloud CLI installed and authenticated:  gcloud auth login
#   2. A Google Cloud project with billing enabled (card required, but the
#      free tier is not charged). New accounts also get $300 credit/90 days.
#   3. A free Neon Postgres database: https://neon.tech -> create project ->
#      copy the *pooled* connection string (hostname contains "-pooler").
#
# Usage:
#   export DATABASE_URL="postgresql://user:pass@ep-xyz-pooler.us-east-2.aws.neon.tech/dbname?sslmode=require"
#   ./deploy-cloudrun.sh
#
# Optional overrides: PROJECT, SERVICE, REGION
set -euo pipefail

SERVICE="${SERVICE:-hero-realms}"
REGION="${REGION:-us-central1}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"

if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no GCP project. Set PROJECT or run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set." >&2
  echo "Create a free Neon Postgres project and export its pooled connection string:" >&2
  echo '  export DATABASE_URL="postgresql://user:pass@ep-xyz-pooler.us-east-2.aws.neon.tech/dbname?sslmode=require"' >&2
  exit 1
fi

echo "Enabling required APIs (idempotent)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com --project "${PROJECT}" >/dev/null

echo "Building and deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 3 \
  --set-env-vars "COOKIE_SECURE=1,DATABASE_URL=${DATABASE_URL}"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" \
  --region "${REGION}" --format 'value(status.url)')"
echo ""
echo "Deployed: ${URL}"
echo "Register two accounts there, create a game, share the invite code, play."

# Post-deploy live QA (Playwright, real browsers against the live URL).
# Runs only here, on deployments — never on a schedule, to avoid pointless
# traffic. Skip with SKIP_E2E=1.
if [[ "${SKIP_E2E:-0}" == "1" ]]; then
  echo "SKIP_E2E=1: skipping post-deploy live QA."
else
  echo ""
  echo "Running post-deploy live QA against ${URL} ..."
  if command -v node >/dev/null 2>&1 && node -e "require('playwright')" 2>/dev/null; then
    BASE_URL="${URL}" node web/e2e/live-qa.mjs || {
      echo "WARNING: post-deploy live QA failed — see output above." >&2
    }
  else
    echo "WARNING: node + playwright not available; skipping live QA." >&2
    echo "Install with: npm i -g playwright && npx playwright install chromium" >&2
  fi
fi
