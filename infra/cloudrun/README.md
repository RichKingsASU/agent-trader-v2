# Cloud Run deploy scaffolding (prod)

This folder provides a clean deploy path for:

- **Market ingestion service** (`market-ingest`)
- **Execution engine service** (`execution-engine`)
- **Optional backfill job + scheduler** (`alpaca-bars-backfill`)

Design goals:

- **ADC only** at runtime (attach a Cloud Run service account; do not use JSON keys).
- **No secrets committed** (this repo only includes env var *names* and empty templates).
- **Consistent deploy scripts** (Docker build → push → `gcloud run deploy`).

See `docs/DEPLOY_GCP.md` for step-by-step deployment and IAM requirements.

## vNEXT: repo-wide non-invasive confirmation

A repo-wide scan shows **no vNEXT-labeled runtime code** (outside vendored dependencies), so vNEXT introduces:
- no imports from live-trading execution code
- no side effects
- no background threads
- no network calls

