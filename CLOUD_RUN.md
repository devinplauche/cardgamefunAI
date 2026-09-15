# Hosting the multiplayer app on Google Cloud Run (free tier)

This is the $0 path: Cloud Run's always-free tier comfortably covers two
people playing nightly, and Neon's free Postgres never expires.

## Why this fits

- Cloud Run free tier: 2M requests, 180k vCPU-seconds, 360k GiB-seconds per
  month. Two nightly players polling every 2.5s use roughly 5% of that.
- Scale-to-zero with ~1-3s cold starts (vs 30-60s on Render's free tier), so
  no uptime-pinger hack is needed.
- The existing `Dockerfile` works unchanged: `web/backend.py` already listens
  on `$PORT` and binds `0.0.0.0` when `PORT` is set, which is exactly what
  Cloud Run injects.
- `--max-instances 3` in the deploy script caps runaway cost if something
  ever goes wrong.

## One-time setup

1. Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install) and
   sign in:
   ```bash
   gcloud auth login
   gcloud projects create hero-realms-game   # or reuse an existing project
   gcloud config set project hero-realms-game
   ```
2. Enable billing on the project in the
   [Cloud Console](https://console.cloud.google.com/billing) (card required;
   the free tier itself is not charged; new accounts also get $300/90 days).
3. Create a free Postgres at [neon.tech](https://neon.tech) (no card needed).
   In the Neon dashboard copy the **pooled** connection string — its hostname
   contains `-pooler` — and append `?sslmode=require` if not already present.
4. (Recommended) set a $1 budget alert in the console so any surprise usage
   emails you instead of billing you.

## Deploy

```bash
export DATABASE_URL="postgresql://user:pass@ep-xyz-pooler.us-east-2.aws.neon.tech/dbname?sslmode=require"
./deploy-cloudrun.sh
```

The script enables the required GCP APIs, builds the container with Cloud
Build (120 free build-minutes/day), and deploys. It prints the public
`https://...run.app` URL when done. `COOKIE_SECURE=1` is set because Cloud
Run terminates TLS.

To redeploy after pulling new changes, just run the script again.

## Play

Open the URL, register an account for yourself and one for your wife, create
a game, and share the 6-character invite code. Games persist in Postgres, so
you can also play async across days.

## Notes

- First load of the night may take a couple of seconds (cold start); after
  that it stays warm while you play.
- The `.gcloudignore` keeps the build upload small; the image itself is the
  same one `render.yaml`/Docker uses.
- If Neon ever feels slow to wake, its free compute suspends after 5 idle
  minutes and resumes in ~0.5s on the first query — not noticeable in play.
