## Timestamp audit report (UTC correctness)

Date: 2026-01-08  
Scope: first-party Python code under `backend/` and `cloudrun_consumer/` (vendored `site-packages/` excluded)

### Executive summary

- **UTC validation**: Canonical timestamp normalization now flows through audited helpers that always return **tz-aware UTC** datetimes.
- **Naive datetime detection**: When a naive datetime (missing `tzinfo` / `utcoffset`) is encountered at normalization boundaries, the system now emits a **rate-limited warning log**.
- **Auto-correction logging**: When timestamps are auto-corrected (naive→UTC attach, non‑UTC→UTC conversion), the system logs `timestamp.naive_assumed_utc` or `timestamp.converted_to_utc`.
- **No breaking changes**: Existing semantics are preserved: **naive datetimes are still assumed to represent UTC** (canonical rule in this repo). The change is observability + consistent UTC coercion.

### What was changed

#### Backend (canonical time layer)

- Added `backend/time/utc_audit.py`:
  - `ensure_utc(dt, source=..., field=..., utc_tz=...) -> datetime`
  - Logs auto-corrections with a per-(kind,source,field) limit.
- Wired audit enforcement into `backend/time/nyse_time.py`:
  - `parse_ts()` and `to_utc()` now call `ensure_utc(...)`.
  - This covers most repo call sites via `backend.common.timeutils.parse_timestamp()` / `ensure_aware_utc()` shims.
- Updated `backend/common/freshness.py`:
  - `coerce_utc()` now uses audited UTC coercion (and still returns `(ts_utc, assumed_utc)`).
- Updated `backend/ops_dashboard_materializer/models.py`:
  - `_parse_rfc3339_best_effort()` now uses audited UTC coercion (so naive/non‑UTC payload timestamps are logged when corrected).
- Updated `backend/ingestion/ingest_heartbeat_handler.py`:
  - Best-effort timestamp parsing and `event_ts_utc` normalization now uses audited UTC coercion.
- Fixed one explicit naive UTC creation:
  - `backend/dataplane/file_store.py` replaced `datetime.utcnow().isoformat() + "Z"` with an explicit UTC-aware timestamp (`datetime.now(timezone.utc)...`).

#### Cloud Run Pub/Sub → Firestore consumer

- Added `cloudrun_consumer/time_audit.py`:
  - Similar `ensure_utc()` behavior, emitting lightweight JSON logs.
- Wired it into:
  - `cloudrun_consumer/event_utils.py`
  - `cloudrun_consumer/main.py` (publishTime parsing)
  - `cloudrun_consumer/firestore_writer.py` (all key datetime fields written to Firestore)
  - `cloudrun_consumer/handlers/system_events.py`

### Logging behavior

#### Event types

- **`timestamp.naive_assumed_utc`**: A naive datetime was observed; we attached UTC tzinfo (assumption preserved).
- **`timestamp.converted_to_utc`**: A timezone-aware non‑UTC datetime was observed; we converted it to UTC.

#### Rate limiting + controls

To avoid log spam in hot paths, audit logs are rate-limited per process:

- **`TIMESTAMP_AUDIT_LOGGING_ENABLED`**: default `true`
- **`TIMESTAMP_AUDIT_LOG_LIMIT_PER_KEY`**: default `5` (per `(kind, source, field)` tuple)

### Findings (static scan highlights)

- **Naive datetime creation (`datetime.utcnow()`)**:
  - Found in `backend/dataplane/file_store.py` and fixed to an explicit UTC-aware timestamp.
- **Silent naive coercion patterns** (`if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)`):
  - Present in multiple ingestion/materialization parsers. The most central parsers are now routed through `ensure_utc(...)` so these situations are observable.

### Limitations / known constraints

- This change does **not** attempt to outlaw naive datetimes globally (would be breaking). Instead it:
  - preserves the repo’s canonical assumption (“naive == UTC”),
  - makes it observable, and
  - ensures outputs at normalization boundaries are tz-aware UTC.
- Full test execution was not possible in this environment due to **missing optional dependencies** (e.g. `pydantic`, `google-cloud-*`, `firebase_admin`, `pytz`, `websockets`) and at least one **pre-existing syntax error** in `backend/marketdata/candles/aggregator.py`.

