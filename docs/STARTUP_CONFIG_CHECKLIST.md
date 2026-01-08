## Startup config checklist (fail-fast)

- **Set required environment variables**
  - **GCP_PROJECT**: required (may be auto-normalized from `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT`, `GCP_PROJECT_ID`, or `PROJECT_ID` at runtime)
  - **SYSTEM_EVENTS_TOPIC**: required (non-empty)
  - **INGEST_FLAG_SECRET_ID**: required (non-empty)
  - **ENV**: required (non-empty)

- **Verify “presence-only” logging**
  - On startup, confirm logs include a `required_env` map of `true/false` values and/or a `missing_env` list.
  - Confirm logs do **not** include values for `GCP_PROJECT`, `SYSTEM_EVENTS_TOPIC`, `INGEST_FLAG_SECRET_ID`, or `ENV`.

- **Fail-fast behavior**
  - If any required env var is missing/blank, the service must exit immediately (non-zero).

