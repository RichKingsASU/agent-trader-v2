# Environment Variable & Secret Access Audit

Scope: full-repo scan for `os.getenv`, `os.environ`, `dotenv` usage, and direct references to `APCA_*` / `DATABASE_URL` (plus adjacent secret/config patterns encountered while enumerating usage). **No code was modified** as part of this audit.

## Executive findings

- **Two “env contract” systems exist**:
  - `backend/common/config.py` defines service-level contracts (Cloud Run ingestor/consumer, strategy-engine, etc.).
  - Many entrypoints additionally read env vars ad-hoc via `os.getenv(...)` with defaults.
  - Recommendation: converge new code on `backend/common/config.py` + `backend/common/env.py` helpers to reduce drift.
- **Alias sprawl is the dominant risk**:
  - Alpaca credentials: `APCA_*` (canonical) vs `ALPACA_*` (aliases) vs legacy `APCA_API_KEY` / `APCA_API_SECRET`.
  - GCP project: `GCP_PROJECT` vs `GOOGLE_CLOUD_PROJECT` vs `GCLOUD_PROJECT` vs `PROJECT_ID` vs `PUBSUB_PROJECT_ID`.
  - Environment labels: `ENV` vs `ENVIRONMENT` vs `APP_ENV` vs `DEPLOY_ENV`.
- **Conflicting naming** (high risk of operator error):
  - `ALPACA_FEED` is used for both **stock feed** (`iex|sip`) and **options feed** (`indicative|opra`), depending on the module.
  - Recommendation: split into `ALPACA_STOCK_FEED` and `ALPACA_OPTIONS_FEED` consistently (and treat `ALPACA_FEED` as deprecated).
- **Hardcoded defaults are common** (some are safe, some can hide misconfig):
  - Safe-ish defaults: paper trading URL, logging level, liveness thresholds, rate limits.
  - Risky defaults: any default that changes runtime behavior silently (e.g., multiple “heartbeat interval” env names, or default topics/IDs in scripts).
- **Secret access patterns found**:
  - **Secret Manager access in code**: `backend/ingestion/vm_ingest.py` reads `VM_INGEST_CONFIG_SECRET_VERSION` and calls Secret Manager `access_secret_version(...)`.
  - **Secret Manager “ID only” config**: `INGEST_FLAG_SECRET_ID` is required by the Cloud Run env contract, but no runtime code path in `cloudrun_ingestor/main.py` currently dereferences it (suggests planned/partial implementation).
  - **Forbidden-in-prod keyfile pattern**: `GOOGLE_APPLICATION_CREDENTIALS` appears in `.env.example` (appropriate for local/CI only).

## Inventory table (File → Variable → Purpose → Runtime dependency)

Notes:
- “Runtime dependency” uses `ingest`, `backfill`, `trading`, or a composite like `ingest+trading`. A small number of entries are `ci/test` when only referenced by tests or CI scripts.
- “Purpose” is inferred from usage context and nearby comments.

| File(s) | Variable name | Purpose | Runtime dependency |
|---|---|---|---|
| `backend/common/agent_mode_guard.py` | `AGENT_MODE` | Hard safety guardrails for agent runtime mode (forbids `EXECUTE`) | trading+ingest |
| `backend/common/agent_mode_guard.py` | `TRADING_MODE` | Paper-trading hard lock (`paper` required unless code-enabled) | trading+ingest |
| `backend/execution_agent/gating.py` | `REPO_ID` | Strict startup gate: must match `agent-trader-v2` | trading |
| `backend/execution_agent/gating.py` | `AGENT_NAME` | Strict startup gate identity (`execution-agent`) | trading |
| `backend/execution_agent/gating.py` | `AGENT_ROLE` | Strict startup gate identity (`execution`) | trading |
| `backend/execution_agent/gating.py` | `EXECUTION_AGENT_ENABLED` | Strict startup gate (must be `"true"`) | trading |
| `backend/execution_agent/gating.py` | `BROKER_EXECUTION_ENABLED` | Strict startup gate: must be present and exactly `"false"` | trading |
| `backend/execution_agent/gating.py` | `EXECUTION_ENABLED` | Strict startup gate: must be present and exactly `"false"` | trading |
| `backend/common/kill_switch.py`, `backend/mission_control/main.py`, `backend/execution/engine.py` | `EXECUTION_HALTED` | Preferred global kill switch (truthy halts execution) | trading |
| `backend/common/kill_switch.py` | `EXECUTION_HALTED_FILE` | Optional file-based kill switch (K8s/ConfigMap style) | trading |
| `backend/common/kill_switch.py`, `backend/mission_control/main.py`, `backend/execution/engine.py` | `EXEC_KILL_SWITCH` | Legacy kill switch (deprecated alias) | trading |
| `backend/common/kill_switch.py`, `backend/mission_control/main.py` | `EXEC_KILL_SWITCH_FILE` | Legacy file-based kill switch alias (deprecated) | trading |
| `backend/execution/engine.py` | `EXECUTION_HALTED_DOC` | Firestore-backed kill switch doc path | trading |
| `backend/execution/engine.py` | `EXEC_KILL_SWITCH_DOC` | Legacy Firestore-backed kill switch doc alias | trading |
| `backend/common/execution_confirm.py` | `EXECUTION_CONFIRM_TOKEN` | Future “live execution confirmation” token gate | trading |
| `backend/execution/engine.py` | `EXEC_DRY_RUN` | Execution engine dry-run toggle (defaults truthy) | trading |
| `backend/execution/engine.py` | `EXEC_TENANT_ID` | Preferred tenant id for execution scoping | trading |
| `backend/execution/engine.py`, `backend/execution/reservations.py`, `scripts/mock_options_feed.py` | `TENANT_ID` | Tenant id fallback for multi-tenant scoping | trading+ingest |
| `backend/execution/engine.py` | `EXEC_UID` | Execution uid/user fallback for gating/accounting | trading |
| `backend/execution/engine.py` | `USER_ID` | UID alias fallback (used when metadata lacks uid) | trading |
| `backend/execution/engine.py` | `EXEC_MAX_DAILY_TRADES` | Risk limit: max trades per day | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_BUDGETS_ENABLED` | Feature flag for budget enforcement | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_BUDGETS_USE_FIRESTORE` | Budget backend selection (Firestore vs other) | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_BUDGETS_FAIL_OPEN` | Budget enforcement failure behavior | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_BUDGET_CACHE_S` | Budget cache TTL seconds | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_DEFAULT_MAX_DAILY_EXECUTIONS` | Default per-day execution count ceiling | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_DEFAULT_MAX_DAILY_CAPITAL_PCT` | Default capital usage ceiling | trading |
| `backend/execution/engine.py` | `EXEC_AGENT_BUDGETS_JSON` | JSON overrides for budgets | trading |
| `backend/common/env.py`, `functions/utils/apca_env.py`, `backend/streams/alpaca_env.py`, multiple scripts/tests | `APCA_API_KEY_ID` | Alpaca API key id (canonical) | ingest+backfill+trading |
| `backend/common/env.py`, `functions/utils/apca_env.py`, `backend/streams/alpaca_env.py`, multiple scripts/tests | `APCA_API_SECRET_KEY` | Alpaca API secret key (canonical) | ingest+backfill+trading |
| `backend/common/env.py`, `functions/utils/apca_env.py`, `backend/streams/alpaca_env.py`, multiple scripts/tests | `APCA_API_BASE_URL` | Alpaca trading base URL (paper URL enforced in some helpers) | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_API_KEY` | Alpaca key alias → normalized to `APCA_API_KEY_ID` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_API_KEY_ID` | Alpaca key alias → normalized to `APCA_API_KEY_ID` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_SECRET_KEY` | Alpaca secret alias → normalized to `APCA_API_SECRET_KEY` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_API_SECRET_KEY` | Alpaca secret alias → normalized to `APCA_API_SECRET_KEY` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_TRADING_HOST` | Alpaca base-url alias → normalized to `APCA_API_BASE_URL` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_API_BASE_URL` | Alpaca base-url alias → normalized to `APCA_API_BASE_URL` | ingest+backfill+trading |
| `backend/common/env.py` | `ALPACA_API_URL` | Alpaca base-url alias → normalized to `APCA_API_BASE_URL` | ingest+backfill+trading |
| `backend/common/env.py` | `APCA_API_KEY` | Legacy Alpaca key alias (non-standard) | ingest+backfill+trading |
| `backend/common/env.py` | `APCA_API_SECRET` | Legacy Alpaca secret alias (non-standard) | ingest+backfill+trading |
| `backend/streams/alpaca_env.py`, `backend/streams/alpaca_option_window_ingest.py`, `scripts/ingest_market_data.py` | `ALPACA_DATA_HOST` | Alpaca data API host (defaults to `https://data.alpaca.markets`) | ingest+backfill |
| `backend/streams/alpaca_quotes_streamer.py`, `backend/streams/alpaca_trade_candle_aggregator.py`, tests | `ALPACA_DATA_FEED` | Alpaca data feed selector (`iex` vs `sip`) | ingest |
| `backend/streams/*.py`, `backend/streams/alpaca_backfill_bars.py`, `scripts/ingest_market_data.py` | `ALPACA_SYMBOLS` | Symbol list for streaming/backfill/ingest jobs | ingest+backfill |
| `backend/streams/alpaca_bars_ingest.py`, `backend/streams/alpaca_backfill_bars.py`, `backend/streams/alpaca_trade_candle_aggregator.py`, `scripts/ingest_market_data.py` | `ALPACA_FEED` | **Conflicting usage**: stock feed in some modules; options feed default (`indicative`) elsewhere | ingest+backfill |
| `backend/streams/alpaca_option_window_ingest.py` | `ALPACA_STOCK_FEED` | Stock feed override when `ALPACA_FEED` is used for options feed | ingest |
| `backend/streams/alpaca_options_chain_ingest.py` | `ALPACA_OPTIONS_FEED` | Options feed selector (e.g., `indicative`, `opra`) | ingest |
| `backend/streams/alpaca_options_chain_ingest.py` | `ALPACA_OPTIONS_MAX_PAGES` | Pagination bound for options-chain fetch | ingest |
| `backend/streams/alpaca_options_chain_ingest.py` | `UNDERLYING` | Underlying symbol for options-chain ingestion | ingest |
| `backend/streams/alpaca_auth_smoke.py`, tests | `ALPACA_DATA_STREAM_WS_URL` | Override websocket URL for Alpaca data streaming | ingest |
| `backend/streams/alpaca_auth_smoke.py`, tests | `ALPACA_AUTH_SMOKE_TIMEOUT_S` | Timeout for Alpaca auth smoke checks | ingest |
| `backend/streams/*`, `backend/streams/alpaca_trade_candle_aggregator.py`, `backend/ingestion/market_data_ingest.py` | `SKIP_ALPACA_AUTH_SMOKE_TESTS` | Skip deterministic Alpaca auth checks at startup | ingest |
| `backend/streams/alpaca_order_smoke_test.py` | `ENABLE_ALPACA_ORDER_SMOKE_TEST_ORDER` | Enable placing a test order (dangerous; should be off by default) | trading |
| `backend/streams/alpaca_option_window_ingest.py` | `OPTION_DTE_MAX` | Options window selection: max days-to-expiration | ingest |
| `backend/streams/alpaca_option_window_ingest.py` | `OPTION_STRIKE_WINDOW` | Options window selection: strike distance window | ingest |
| `backend/streams/alpaca_option_window_ingest.py` | `ALPACA_PAPER` | Boolean hint for paper/live behavior in options ingest | ingest |
| `backend/streams/alpaca_backfill_bars.py`, `functions/backtester.py`, `scripts/run_backtest_example.py`, `scripts/place_test_order.py` | `ALPACA_BACKFILL_DAYS` | Backfill horizon length in days | backfill |
| `backend/common/config.py`, `backend/strategy_engine/config.py`, `backend/streams/*.py`, `backend/execution/engine.py`, scripts/tests | `DATABASE_URL` | Postgres connection string | ingest+backfill+trading |
| `backend/dataplane/file_store.py` | `DATA_PLANE_ROOT` | Root directory for local data-plane storage | ingest+backfill |
| `backend/strategy_engine/config.py` | `STRATEGY_NAME` | Strategy selection name (default `naive_flow_trend`) | trading |
| `backend/strategy_engine/config.py` | `STRATEGY_SYMBOLS` | Strategy symbol universe | trading |
| `backend/strategy_engine/config.py` | `STRATEGY_BAR_LOOKBACK_MINUTES` | Strategy bar lookback window | trading |
| `backend/strategy_engine/config.py` | `STRATEGY_FLOW_LOOKBACK_MINUTES` | Strategy flow lookback window | trading |
| `backend/common/env.py`, `backend/streams_bridge/config.py`, `backend/strategy_engine/config.py`, `functions/utils/watchdog.py` | `VERTEX_AI_MODEL_ID` | Vertex AI model id (defaults to `gemini-2.5-flash`) | trading+ingest |
| `backend/common/env.py`, `backend/streams_bridge/config.py` | `VERTEX_AI_PROJECT_ID` | Vertex AI project override (fallbacks to Firebase/ADC) | trading+ingest |
| `backend/common/env.py`, `backend/streams_bridge/config.py`, `functions/utils/watchdog.py` | `VERTEX_AI_LOCATION` | Vertex AI region (default `us-central1`) | trading+ingest |
| `backend/common/env.py`, `backend/persistence/firebase_client.py`, multiple services | `FIREBASE_PROJECT_ID` | Canonical Firebase/Firestore project id | ingest+trading |
| `backend/common/env.py`, `backend/persistence/firebase_client.py`, `backend/contracts/ops_alerts.py` | `FIRESTORE_PROJECT_ID` | Legacy Firestore project id alias | ingest+trading |
| `backend/common/env.py`, many services | `GOOGLE_CLOUD_PROJECT` | GCP project id fallback (ADC default) | ingest+trading |
| `backend/persistence/firebase_client.py`, functions, tests | `GCLOUD_PROJECT` | GCP project id alias (fallback) | ingest+trading |
| `backend/.env.example`, docs | `GOOGLE_APPLICATION_CREDENTIALS` | ADC keyfile path (local/CI only; avoid in prod) | ingest+trading |
| `tests/test_firestore_emulator_integration.py` | `FIRESTORE_EMULATOR_HOST` | Enable Firestore emulator integration testing | ci/test |
| `scripts/data_plane_smoke_test.py` | `PUBSUB_EMULATOR_HOST` | Enable Pub/Sub emulator for smoke tests | ci/test |
| `backend/common/config.py`, `cloudrun_ingestor/main.py`, `cloudrun_consumer/main.py`, `scripts/data_plane_smoke_test.py` | `GCP_PROJECT` | Canonical project id for Cloud Run ingestion/consumer | ingest |
| `backend/common/config.py`, `backend/ingestion/config.py`, `cloudrun_ingestor/main.py`, `cloudrun_consumer/main.py`, scripts | `SYSTEM_EVENTS_TOPIC` | Pub/Sub topic for system events | ingest |
| `backend/common/config.py`, `backend/ingestion/config.py`, `cloudrun_ingestor/main.py` | `MARKET_TICKS_TOPIC` | Pub/Sub topic for tick events | ingest |
| `backend/common/config.py`, `backend/ingestion/config.py`, `cloudrun_ingestor/main.py` | `MARKET_BARS_1M_TOPIC` | Pub/Sub topic for 1-minute bars | ingest |
| `backend/common/config.py`, `backend/ingestion/config.py`, `cloudrun_ingestor/main.py` | `TRADE_SIGNALS_TOPIC` | Pub/Sub topic for trade signals | ingest |
| `backend/common/config.py`, `backend/ingestion/config.py`, `cloudrun_ingestor/main.py`, `cloudrun_consumer/main.py` | `INGEST_FLAG_SECRET_ID` | Intended Secret Manager secret id for ingest enable/disable flag | ingest |
| `backend/ingestion/config.py` | `HEARTBEAT_INTERVAL_SECONDS` / `HEARTBEAT_INTERVAL_S` | Ingestor heartbeat interval (supports two names) | ingest |
| `backend/ingestion/config.py` | `FLAG_CHECK_INTERVAL_SECONDS` / `FLAG_CHECK_INTERVAL_S` | Ingest flag poll interval (supports two names) | ingest |
| `backend/ingestion/market_data_ingest.py` | `INGEST_HEARTBEAT_TOPIC_ID` | Optional Pub/Sub topic id for synthetic ingest heartbeats | ingest |
| `backend/ingestion/market_data_ingest.py` | `INGEST_PIPELINE_ID` | Pipeline identity used in ingest heartbeat events | ingest |
| `backend/ingestion/market_data_ingest.py` | `INGEST_HEARTBEAT_PUBLISH_TIMEOUT_S` | Timeout for publishing heartbeat to Pub/Sub | ingest |
| `backend/ingestion/pubsub_event_ingestion_service.py` | `INGEST_HEARTBEAT_SUBSCRIPTION_ID` | Subscription short id used to filter ingest-heartbeat messages | ingest |
| `backend/common/ingest_switch.py` | `INGEST_ENABLED` | Soft ingest pause switch (env) | ingest |
| `backend/common/ingest_switch.py` | `INGEST_ENABLED_FILE` | Soft ingest pause switch (file path) | ingest |
| `backend/ingestion/market_data_ingest.py` | `INGEST_ENABLED_POLL_S` | Poll interval for ingest enabled state | ingest |
| `cloudrun_consumer/main.py`, `backend/common/config.py` | `FIRESTORE_DATABASE` | Firestore database id (defaults to `(default)`) | ingest |
| `cloudrun_consumer/main.py`, `backend/common/config.py` | `FIRESTORE_COLLECTION_PREFIX` | Prefix for Firestore collections (namespacing) | ingest |
| `cloudrun_consumer/main.py`, `backend/common/config.py`, scripts | `DEFAULT_REGION` | Default region label for materializer | ingest |
| `cloudrun_consumer/main.py` | `SUBSCRIPTION_TOPIC_MAP` | Subscription→topic mapping config (JSON/text) | ingest |
| `cloudrun_consumer/main.py` | `FIRESTORE_RETRY_MAX_ATTEMPTS` | Firestore retry tuning | ingest |
| `cloudrun_consumer/main.py` | `FIRESTORE_RETRY_INITIAL_BACKOFF_S` | Firestore retry tuning | ingest |
| `cloudrun_consumer/main.py` | `FIRESTORE_RETRY_MAX_BACKOFF_S` | Firestore retry tuning | ingest |
| `cloudrun_consumer/main.py` | `FIRESTORE_RETRY_MAX_TOTAL_S` | Firestore retry tuning | ingest |
| `cloudrun_consumer/main.py`, `backend/common/config.py` | `DLQ_SAMPLE_RATE` | DLQ sampling rate | ingest |
| `cloudrun_consumer/main.py`, `backend/common/config.py` | `DLQ_SAMPLE_TTL_HOURS` | DLQ marker TTL hours | ingest |
| `cloudrun_consumer/main.py` | `REPLAY_RUN_ID` | Enables replay markers grouping | ingest |
| `backend/ingestion/market_data_ingest.py` | `MONITORED_SYMBOLS` | Symbol list override for market-data-ingest (fallbacks to `ALPACA_SYMBOLS`) | ingest |
| `backend/ingestion/market_data_ingest.py` | `DRY_RUN` | Disable external writes; simulate behavior without creds | ingest |
| `backend/ingestion/market_data_ingest.py` | `PER_SYMBOL_MIN_INTERVAL_MS` | Per-symbol write throttle interval | ingest |
| `backend/ingestion/market_data_ingest.py` | `GLOBAL_WRITES_PER_SEC` | Global write rate limit | ingest |
| `backend/ingestion/market_data_ingest.py` | `GLOBAL_BURST` | Global rate-limit burst capacity | ingest |
| `backend/ingestion/market_data_ingest.py` | `FLUSH_INTERVAL_MS` | Coalescing flush interval | ingest |
| `backend/ingestion/market_data_ingest.py` | `HEARTBEAT_INTERVAL_S` | Firestore heartbeat interval | ingest |
| `backend/ingestion/market_data_ingest.py` | `FIRESTORE_LIVE_QUOTES_COLLECTION` / `FIRESTORE_LATEST_COLLECTION` | Firestore collection name for latest quotes (defaults `live_quotes`) | ingest |
| `backend/ingestion/market_data_ingest.py` | `STOP_AFTER_SECONDS` | Auto-stop after N seconds (test/safety) | ingest |
| `backend/ingestion/market_data_ingest.py`, `backend/streams/alpaca_quotes_streamer.py` | `RECONNECT_BACKOFF_BASE_S` | Reconnect backoff base seconds | ingest |
| `backend/ingestion/market_data_ingest.py`, `backend/streams/alpaca_quotes_streamer.py` | `RECONNECT_BACKOFF_MAX_S` | Reconnect backoff max seconds | ingest |
| `backend/streams/alpaca_quotes_streamer.py` | `RECONNECT_MAX_RETRY_WINDOW_S` | Reconnect retry window cap | ingest |
| `backend/ingestion/market_data_ingest.py`, `backend/streams/alpaca_quotes_streamer.py` | `RECONNECT_MAX_ATTEMPTS` | Reconnect attempt cap | ingest |
| `backend/ingestion/market_data_ingest.py`, `backend/streams/alpaca_quotes_streamer.py` | `RECONNECT_MIN_SLEEP_S` | Minimum reconnect sleep | ingest |
| `backend/ops_dashboard_materializer/service.py` | `DASHBOARD_MATERIALIZER_ROUTES_JSON` | Route config JSON for dashboard materializer | trading+ingest |
| `backend/risk_allocator/allocator.py` | `ALLOCATOR_DEFAULT_QTY` | Default position sizing quantity | trading |
| `backend/news_ingest/main.py` | `NEWS_INGEST_ONCE` | Run news ingestion once then exit | ingest |
| `backend/news_ingest/service.py` | `HEARTBEAT_LOG_INTERVAL_S` | News ingest heartbeat log interval | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_TIMEFRAMES` | Candle aggregation timeframes | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_LATENESS_SECONDS` | Allowed event lateness window | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_MARKET_TZ` | Market timezone label | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_SESSION_DAILY` | Daily session semantics toggle | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_FLUSH_INTERVAL_SEC` | Periodic flush interval | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `CANDLE_DB_BATCH_MAX` | DB batch size bound | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `ENABLE_TICK_STORE` | Enable local tick store | ingest |
| `backend/streams/alpaca_trade_candle_aggregator.py` | `ENABLE_CANDLE_STORE` | Enable local candle store | ingest |
| `backend/common/config.py`, `cloudrun_ingestor/main.py`, `cloudrun_consumer/main.py`, `backend/execution_agent/gating.py` | `ENV` | Environment label (required for cloudrun-consumer contract) | ingest+trading |
| `backend/common/agent_mode_guard.py`, `backend/messaging/publisher.py`, `backend/execution_agent/gating.py` | `ENVIRONMENT` / `APP_ENV` / `DEPLOY_ENV` | Environment label aliases used in logs/identity | ingest+trading |
| `backend/common/config.py`, multiple services | `LOG_LEVEL` | Log verbosity | ingest+trading |
| `cloudrun_consumer/main.py` | `PORT` | HTTP port (Cloud Run) | ingest |
| `backend/common/lifecycle.py`, `backend/common/cloudrun_perf.py`, many services | `K_SERVICE` / `K_REVISION` / `K_CONFIGURATION` | Cloud Run identity fields | ingest+trading |
| `backend/messaging/envelope.py`, `backend/common/runtime_fingerprint.py`, many services | `GIT_SHA` / `GITHUB_SHA` / `COMMIT_SHA` | Build SHA labeling | ingest+trading |
| `backend/common/audit_logging.py` | `BUILD_ID` | Build id for ops/status | ingest+trading |
| `backend/common/audit_logging.py` | `BUILD_FINGERPRINT` | Optional build fingerprint override | ingest+trading |
| `backend/common/audit_logging.py` | `IMAGE_DIGEST` / `CONTAINER_IMAGE` / `IMAGE_TAG` | Image identity labeling | ingest+trading |
| `backend/common/replay_events.py` | `TRACE_ID` | Process trace id / correlation id seed | ingest+trading |
| `backend/messaging/envelope.py` | `ALLOW_LEGACY_SCHEMALESS_ENVELOPE` | Back-compat allowance for legacy envelopes | ingest+trading |
| `backend/messaging/publisher.py` | `PUBSUB_SCHEMA_VERSION` | Pub/Sub envelope schema version (default `"1"`) | ingest |
| `backend/strategy_engine/service.py` | `WORKLOAD` | Workload label in identity | trading |
| `backend/strategy_engine/service.py` | `MARKETDATA_HEARTBEAT_URL` / `MARKETDATA_HEALTH_URL` | Dependency endpoint selection (local default if missing) | trading |
| `backend/strategy_engine/service.py` | `MARKETDATA_HEALTH_TIMEOUT_SECONDS` | Timeout for marketdata health fetch | trading |
| `backend/strategy_engine/service.py` | `OBSERVE_HEARTBEAT_INTERVAL_S` | Observe-mode heartbeat cadence | trading |
| `backend/strategy_engine/service.py` | `OBSERVE_HEARTBEAT_PATH` | Observe-mode heartbeat file path | trading |
| `backend/strategy_engine/service.py` | `OPS_STATUS_MARKETDATA_POLL_SECONDS` | Poll cadence for ops/status marketdata freshness | trading |
| `backend/strategy_engine/service.py` | `OPS_STATUS_MARKETDATA_TIMEOUT_SECONDS` | Timeout for ops/status marketdata fetch | trading |
| `backend/strategy_engine/service.py` | `OPS_HEARTBEAT_LOG_INTERVAL_S` | Ops heartbeat log interval | trading |
| `backend/strategy_engine/service.py`, `backend/ingestion/market_data_ingest_service.py`, `backend/ingestion/pubsub_event_ingestion_service.py`, `cloudrun_consumer/main.py` | `LIVEZ_MAX_AGE_S` | Liveness max “loop wedged” age seconds | ingest+trading |
| `backend/strategy_engine/service.py`, `backend/execution/engine.py` | `MARKETDATA_STALE_THRESHOLD_S` | Marketdata staleness threshold for gating/status | trading |
| `backend/strategy_engine/service.py` | `OPS_HEARTBEAT_TTL_S` | Ops heartbeat TTL seconds | trading |
| `backend/streams_bridge/firestore_writer.py` | `DRY_RUN` | Disable writes (stream bridge) | ingest |
| `backend/streams_bridge/config.py` | `PRICE_STREAM_URL` | Upstream price stream endpoint | ingest |
| `backend/streams_bridge/config.py` | `OPTIONS_FLOW_URL` | Upstream options-flow endpoint | ingest |
| `backend/streams_bridge/config.py` | `OPTIONS_FLOW_API_KEY` | API key for options-flow upstream | ingest |
| `backend/streams_bridge/config.py` | `NEWS_STREAM_URL` | Upstream news stream endpoint | ingest |
| `backend/streams_bridge/config.py` | `NEWS_STREAM_API_KEY` | API key for news upstream | ingest |
| `backend/streams_bridge/config.py` | `ACCOUNT_UPDATES_URL` | Upstream account updates endpoint | ingest |
| `backend/streams_bridge/config.py` | `ACCOUNT_UPDATES_API_KEY` | API key for account updates upstream | ingest |
| `backend/ingestion/vm_ingest.py` | `PUBSUB_PROJECT_ID` | Pub/Sub project selection (fallback to ADC env aliases) | ingest |
| `backend/ingestion/vm_ingest.py` | `PUBSUB_SUBSCRIPTION_ID` | Subscription id to consume | ingest |
| `backend/ingestion/vm_ingest.py` | `FIRESTORE_COLLECTION` | Firestore collection for raw event writes (default `vm_ingest_events`) | ingest |
| `backend/ingestion/vm_ingest.py` | `VM_INGEST_CONFIG_SECRET_VERSION` | Secret Manager version name to load JSON config | ingest |
| `backend/ingestion/vm_ingest.py` | `VM_INGEST_MAX_IN_FLIGHT` | Subscriber flow-control max messages | ingest |
| `scripts/mock_options_feed.py` | `NATS_URL` | NATS connection URL (local dev/testing) | ci/test |
| `functions/gamma_scalper.py` | `ENABLE_DANGEROUS_FUNCTIONS` | Feature flag to enable dangerous functions | trading |
| `functions/ticker_service.py`, `functions/ticker_service_example.py` | `TICKER_SYMBOLS` | Ticker service symbols | ingest |
| `scripts/data_plane_smoke_test.py` | `SMOKE_MODE` / `SMOKE_TIMEOUT_S` / `SMOKE_CONSUMER_PORT` / `SMOKE_SERVICE_ID` | Smoke test harness tuning | ci/test |
| `scripts/agent_executor.py` | `REPO_DIR` | Override repo directory for agent executor | ci/test |
| `backend/mission_control/main.py` | `EVENT_BUFFER_MAXLEN` | Event buffer sizing | trading |
| `backend/mission_control/main.py` | `POLL_MAX_CONCURRENCY` | Agent polling concurrency | trading |
| `backend/mission_control/main.py` | `AGENTS_CONFIG_PATH` | Path to agents config YAML | trading |
| `backend/mission_control/main.py` | `POLL_INTERVAL_SECONDS` | Poll loop interval | trading |
| `backend/mission_control/main.py` | `PER_AGENT_TIMEOUT_SECONDS` | Agent poll timeout | trading |
| `backend/mission_control/main.py` | `DEPLOY_REPORT_PATH` | Deploy report output path | trading |
| `tests/test_alpaca_auth_smoke.py` | `RUN_ALPACA_AUTH_SMOKE_TESTS` | Enable Alpaca auth smoke tests | ci/test |
| `tests/test_firecracker_runner_smoke.py` | `FIRECRACKER_BIN` / `FC_KERNEL_IMAGE` / `FC_ROOTFS_IMAGE` | Firecracker runner smoke-test prerequisites | ci/test |
| `scripts/ci/check_python_runtime_guardrails.py` | `GITHUB_BASE_REF` / `GITHUB_REF_NAME` | GitHub Actions branch/ref metadata | ci/test |
| `scripts/*.py`, `backend/streams/test_live_quote_ingest.py`, `zzz-utbot_atr_live_1M_Rev_F22.py` | `dotenv` / `load_dotenv(...)` | Local env loading from `.env` / `.env.local` | ci/test |

## Duplicate variables, naming conflicts, hardcoded defaults

### Duplicate / alias sets (recommend canonicalization)

- **Alpaca credentials**
  - **Canonical**: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `APCA_API_BASE_URL`
  - **Aliases present**: `ALPACA_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_SECRET_KEY`, `ALPACA_API_SECRET_KEY`, `ALPACA_TRADING_HOST`, `ALPACA_API_BASE_URL`, `ALPACA_API_URL`
  - **Legacy**: `APCA_API_KEY`, `APCA_API_SECRET`
- **Project id**
  - `GCP_PROJECT` vs `GOOGLE_CLOUD_PROJECT` vs `GCLOUD_PROJECT` vs `PROJECT_ID` vs `PUBSUB_PROJECT_ID`
  - Code normalizes some, but not consistently across services.
- **Environment label**
  - `ENV` vs `ENVIRONMENT` vs `APP_ENV` vs `DEPLOY_ENV`
- **Kill switch**
  - Preferred: `EXECUTION_HALTED` / `EXECUTION_HALTED_FILE`
  - Legacy: `EXEC_KILL_SWITCH` / `EXEC_KILL_SWITCH_FILE` / `EXEC_KILL_SWITCH_DOC`

### Conflicting naming (high risk)

- **`ALPACA_FEED` meaning changes by module**
  - Stock feed expected: `iex|sip` (common in streams/backfill).
  - Options feed defaulted to `indicative` in `backend/streams/alpaca_option_window_ingest.py`.
  - This can cause silent misconfiguration when one deployment sets `ALPACA_FEED` expecting stock semantics.

### Hardcoded defaults (selected examples)

- **Mode/identity defaults (can mask misconfig)**
  - Many services default `ENV` to `unknown` or `prod` if unset (logging-only; usually fine).
  - Some services default `AGENT_NAME`/`AGENT_ROLE` for logs/identity.
- **Operational defaults**
  - `LIVEZ_MAX_AGE_S` defaults vary by service (5/30/60).
  - Various reconnect/backoff defaults (`RECONNECT_*`) and throttles (`GLOBAL_WRITES_PER_SEC`, etc.).
- **Potentially risky defaults**
  - `MARKETDATA_HEARTBEAT_URL` has a local default (`http://127.0.0.1:8080/heartbeat`) in `backend/strategy_engine/service.py`; if deployed without setting it, the service will appear “healthy” but won’t reach marketdata in prod.

## Recommendations (KEEP / REPLACE / REMOVE)

Guidelines used:
- **KEEP**: canonical, intentionally supported, or required by env contracts.
- **REPLACE**: aliases/legacy names should be replaced by canonical names in deploy artifacts (keep code-side alias support temporarily).
- **REMOVE**: deprecated names or unused contract items that create drift (remove from deployment manifests and docs; code removal would be a follow-on change, not performed here).

### Per-variable recommendations (high-signal set)

| Variable | Recommendation | Rationale / notes |
|---|---|---|
| `APCA_API_KEY_ID` | KEEP | Canonical Alpaca key id; required by multiple runtimes. |
| `APCA_API_SECRET_KEY` | KEEP | Canonical Alpaca secret; required by multiple runtimes. |
| `APCA_API_BASE_URL` | KEEP | Canonical Alpaca base URL; paper URL enforcement exists in some helpers. |
| `ALPACA_API_KEY`, `ALPACA_API_KEY_ID` | REPLACE | Use `APCA_API_KEY_ID` everywhere in infra/manifests. Keep alias support only for migration. |
| `ALPACA_SECRET_KEY`, `ALPACA_API_SECRET_KEY` | REPLACE | Use `APCA_API_SECRET_KEY` canonically. |
| `ALPACA_TRADING_HOST`, `ALPACA_API_BASE_URL`, `ALPACA_API_URL` | REPLACE | Use `APCA_API_BASE_URL` canonically. |
| `APCA_API_KEY`, `APCA_API_SECRET` | REMOVE | Legacy non-standard names; increases drift and accidental mismatch risk. |
| `DATABASE_URL` | KEEP | Canonical DB connection string; required by multiple services. |
| `GCP_PROJECT` | KEEP | Canonical for Cloud Run ingestion/consumer; normalize from ADC aliases where needed. |
| `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT`, `PROJECT_ID`, `PUBSUB_PROJECT_ID` | REPLACE | Prefer `GCP_PROJECT` (service-level) and/or `FIREBASE_PROJECT_ID` (Firestore). Keep fallbacks for portability. |
| `FIREBASE_PROJECT_ID` | KEEP | Canonical Firestore project id in this repo; use helper resolution consistently. |
| `FIRESTORE_PROJECT_ID` | REPLACE | Treat as legacy alias; migrate manifests to `FIREBASE_PROJECT_ID`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | REPLACE | **Local/CI only**; in prod prefer attached service account / ADC. Treat as forbidden-in-prod. |
| `AGENT_MODE` | KEEP | Required safety gate; do not default silently. |
| `TRADING_MODE` | KEEP | Required safety gate; paper lock should remain explicit. |
| `EXECUTION_HALTED`, `EXECUTION_HALTED_FILE` | KEEP | Preferred kill switch surfaces. |
| `EXEC_KILL_SWITCH`, `EXEC_KILL_SWITCH_FILE`, `EXEC_KILL_SWITCH_DOC` | REMOVE | Deprecated aliases; keep only during migration windows. |
| `ALPACA_FEED` | REPLACE | Split meaning: use `ALPACA_STOCK_FEED` and `ALPACA_OPTIONS_FEED`; reserve `ALPACA_FEED` for one meaning only (recommend deprecate). |
| `ALPACA_DATA_FEED` | KEEP | Explicit data-stream feed selector; avoid overloading `ALPACA_FEED`. |
| `SYSTEM_EVENTS_TOPIC`, `MARKET_TICKS_TOPIC`, `MARKET_BARS_1M_TOPIC`, `TRADE_SIGNALS_TOPIC` | KEEP | Core ingest routing. |
| `INGEST_FLAG_SECRET_ID` | REPLACE | Either implement dereference at runtime (Secret Manager read) **or** remove from required contract if not used. Current state suggests drift. |
| `INGEST_ENABLED`, `INGEST_ENABLED_FILE` | KEEP | Operational pause switch; separate from global kill switch. |
| `VM_INGEST_CONFIG_SECRET_VERSION` | KEEP | Explicit Secret Manager access path; keep as the “secret pointer”, not raw secrets. |
| `OPTIONS_FLOW_API_KEY`, `NEWS_STREAM_API_KEY`, `ACCOUNT_UPDATES_API_KEY` | KEEP | Secrets; ensure supplied via Secret Manager rather than plain env in prod. |
| `MARKETDATA_HEARTBEAT_URL`, `MARKETDATA_HEALTH_URL` | KEEP | Required for strategy-engine correctness in prod; avoid relying on local defaults. |

## Suggested next steps (no code changes in this task)

- **Standardize env var contract usage**: consolidate service startup env validation to `backend/common/config.py` across entrypoints (reduce ad-hoc `os.getenv` reads).
- **Rename conflicting feed variables**: deprecate `ALPACA_FEED` in favor of `ALPACA_STOCK_FEED` + `ALPACA_OPTIONS_FEED`.
- **Tighten defaults for production**: for dependency URLs (`MARKETDATA_*`), require explicit env values in prod deploy manifests to avoid silent localhost defaults.
- **Clean up deprecated names**: phase out legacy kill-switch envs and legacy Alpaca envs from deployment artifacts.

