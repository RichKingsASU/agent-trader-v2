# Secrets Contract (authoritative)

This repo enforces a **single, strict contract** for secret values via `backend.common.secrets.get_secret(...)`.

Rules:
- **No secrets are resolved at import time** (secrets are loaded only when runtime code calls `get_secret`).
- **No direct `os.getenv(...)` / `os.environ[...]` access for secrets** (all secret reads go through `backend.common.secrets`).
- **Invalid secret names hard-fail** with an explicit error (use env/config helpers for non-secret runtime configuration).

## Valid secrets

| Secret name | Purpose | Required/Optional | Used by |
|---|---|---|---|
| `DATABASE_URL` | Postgres connection string (includes credentials). | **REQUIRED** | `backend/execution/engine.py`, `backend/strategy_engine/config.py`, `backend/utils/ops_markers.py`, `backend/strategy/naive_strategy_driver.py`, `backend/streams/alpaca_option_window_ingest.py`, `backend/streams/alpaca_quotes_streamer.py`, `backend/tools/stream_dummy_market_data.py`, `backend/tools/test_insert_market_candle.py`, `scripts/insert_paper_order.py`, `scripts/smoke.sh`, `tests/test_deployment.py` |
| `APCA_API_KEY_ID` | Alpaca API key id (trading + data auth). | **REQUIRED** | `backend/common/env.py`, `backend/execution/engine.py`, `backend/streams/alpaca_env.py`, `scripts/*`, `functions/*` |
| `APCA_API_SECRET_KEY` | Alpaca API secret key (trading + data auth). | **REQUIRED** | `backend/common/env.py`, `backend/execution/engine.py`, `backend/streams/alpaca_env.py`, `scripts/*`, `functions/*` |
| `APCA_API_BASE_URL` | Alpaca trading base URL (paper/live host selector). | **OPTIONAL** (default: `https://paper-api.alpaca.markets`) | `backend/common/env.py`, `backend/execution/engine.py`, `backend/streams/alpaca_option_window_ingest.py`, `scripts/*`, `functions/*` |
| `ALPACA_DATA_HOST` | Alpaca data host override (REST data base). | **OPTIONAL** (default: `https://data.alpaca.markets`) | `backend/streams/alpaca_env.py`, `scripts/ingest_market_data.py` |
| `ALPACA_DATA_FEED` | Alpaca data feed selector (e.g. `iex`/`sip`). | **OPTIONAL** (default: `iex`) | `backend/streams/alpaca_auth_smoke.py`, `backend/streams/alpaca_quotes_streamer.py`, `tests/test_alpaca_auth_smoke.py` |
| `ALPACA_DATA_STREAM_WS_URL` | Alpaca data websocket URL override. | **OPTIONAL** (default: empty) | `backend/streams/alpaca_auth_smoke.py`, `tests/test_alpaca_auth_smoke.py` |
| `ALPACA_EQUITIES_FEED` | Equities feed selector (canonical; avoids `ALPACA_FEED` ambiguity). | **OPTIONAL** (default: `iex`) | `backend/common/secrets.py` (helper), `backend/streams/*`, `scripts/ingest_market_data.py` |
| `ALPACA_OPTIONS_FEED` | Options feed selector (canonical; avoids `ALPACA_FEED` ambiguity). | **OPTIONAL** (default: empty) | `backend/common/secrets.py` (helper), `backend/streams/*`, `scripts/ingest_market_data.py` |
| `EXECUTION_CONFIRM_TOKEN` | Live-execution confirmation token (guardrail / future-only). | **OPTIONAL** (default: empty) | `backend/common/execution_confirm.py`, `backend/execution/engine.py` |
| `EXEC_AGENT_ADMIN_KEY` | Enables auth for execution-service admin endpoints (`X-Exec-Agent-Key`). | **OPTIONAL** (default: empty) | `backend/services/execution_service/app.py` |
| `EXEC_IDEMPOTENCY_STORE_ID` | Idempotency store id (if using external idempotency store). | **OPTIONAL** (default: empty) | `backend/execution/engine.py` |
| `EXEC_IDEMPOTENCY_STORE_KEY` | Idempotency store auth key/secret (if using external idempotency store). | **OPTIONAL** (default: empty) | `backend/execution/engine.py` |
| `QUIVER_API_KEY` | Quiver Quantitative API key for congressional disclosures ingest. | **OPTIONAL** (default: empty; enables mock mode when missing) | `backend/ingestion/congressional_disclosures.py` |
| `FRED_API_KEY` | FRED API key for macro scraper enrichment. | **OPTIONAL** (default: empty; skips FRED fetch when missing) | `functions/utils/macro_scraper.py` |
| `NEWS_API_KEY` | API key for news-ingest stub/client. | **OPTIONAL** (default: empty) | `backend/news_ingest/config.py` |
| `OPTIONS_FLOW_API_KEY` | API key for options flow stream source. | **OPTIONAL** (default: empty) | `backend/streams_bridge/config.py` |
| `NEWS_STREAM_API_KEY` | API key for news stream source. | **OPTIONAL** (default: empty) | `backend/streams_bridge/config.py` |
| `ACCOUNT_UPDATES_API_KEY` | API key for account updates stream source. | **OPTIONAL** (default: empty) | `backend/streams_bridge/config.py` |

## Invalid secret names (must NOT be requested via `backend.common.secrets`)

These are **runtime configuration** values. Attempting to call `get_secret(...)` with any of these names will hard-fail with an explicit “invalid secret name” error.

| Name | What it is | Where to read it |
|---|---|---|
| `GCP_PROJECT`, `GOOGLE_CLOUD_PROJECT`, `FIREBASE_PROJECT_ID`, `FIRESTORE_PROJECT_ID`, `PUBSUB_PROJECT_ID` | Project identifiers | `backend.common.env.get_env(...)` / `os.getenv(...)` |
| `SYSTEM_EVENTS_TOPIC`, `MARKET_TICKS_TOPIC`, `MARKET_BARS_1M_TOPIC`, `TRADE_SIGNALS_TOPIC`, `INGEST_FLAG_SECRET_ID` | Cloud Run / PubSub topic routing & ingest toggle | `backend.common.env.get_env(...)` / `backend.common.config.validate_or_exit(...)` |
| Any other non-listed name | Not part of the secrets contract | Add it to the table above **only if it is truly a secret**; otherwise keep it as runtime config |

