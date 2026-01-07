## News ingestion service (OBSERVE-only)

### What it is

`backend/news_ingest/` is a **standalone** poller that ingests raw news events from a (stubbed) news API client and stores them as **append-only NDJSON**.

- **No strategy coupling**: does not import `backend/strategy_engine`, `backend/strategies`, or any signal/proposal writer.
- **No execution paths**: does not import `backend/execution*` or any broker clients.
- **OBSERVE enforced**: startup fails unless `AGENT_MODE=OBSERVE`.

### Run locally

```bash
export AGENT_MODE=OBSERVE
export DATA_PLANE_ROOT=./data

# One poll (useful for smoke tests)
export NEWS_INGEST_ONCE=true
python -m backend.news_ingest
```

### Storage layout

- **Events**: `${DATA_PLANE_ROOT:-data}/news/YYYY/MM/DD/events.ndjson`
- **Cursor**: `${NEWS_INGEST_CURSOR_PATH:-${DATA_PLANE_ROOT:-data}/news/cursor.json}`

Each stored line is:

- `received_at_utc`: ingestion timestamp (UTC)
- `source`: configured source name
- `raw`: raw event payload from the news client

### Config (env)

- `AGENT_MODE` (**required**, must be `OBSERVE`)
- `NEWS_INGEST_POLL_INTERVAL_S` (default `30`)
- `NEWS_INGEST_MAX_EVENTS_PER_POLL` (default `200`)
- `DATA_PLANE_ROOT` (default `data`)
- `NEWS_INGEST_CURSOR_PATH` (default `${DATA_PLANE_ROOT}/news/cursor.json`)
- `NEWS_INGEST_SOURCE` (default `news-api-stub`)
- `NEWS_API_BASE_URL` (default `https://example.invalid`, placeholder)
- `NEWS_API_KEY` (optional, placeholder)

