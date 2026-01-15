## Repository Entry-Point / Unused-File Audit

Date: 2026-01-15  
Scope (per request): `scripts/*.py`, `backend/streams/*.py`, `backend/ingestion/*.py`, `cloudrun_ingestor/*.py`, `functions/*.py`, plus any `__main__` blocks repo-wide.

### Method (what “verified” means)

- **Non-empty**: file contains non-whitespace.
- **Has real logic**: heuristic check (more than only docstring/imports/`pass`/print-only).
- **Imports resolve**:
  - **Static**: `importlib.util.find_spec()` (no code execution) to flag obviously missing modules.
  - **Guaranteed runtime failures**: flagged files that reference `logging` but **do not import `logging`**.
  - External dependencies (FastAPI, Google Cloud, Firebase, Alpaca, etc.) may be missing in this runtime; those are reported as “external deps required”.

### Risk levels (deletion guidance)

- **LOW**: broken/stubbed/unreferenced artifacts; deletion very unlikely to impact runtime.
- **MED**: likely manual/ad-hoc or example/demo; deletion might affect workflows/docs.
- **HIGH**: likely production/service entrypoint or referenced by deployment/ops; do not delete.

## Executive summary

- **Empty files (in scope)**: none found.
- **Critical broken/not-importable entrypoints** (independent of deletion risk):
  - `functions/ingest_alpaca.py`: **syntax error** (contains `def-SECRET- ...`).
  - `backend/ingestion/pubsub_event_ingestion_service.py`: **incomplete stub** (ends with `# ... rest of the file ...`), imports missing internal module `backend.common.pubsub_publisher`, and uses `logging` without importing it.
  - `backend/ingestion/pubsub_event_store.py`: uses `logging` without importing it; also imports missing `backend.common.pubsub_publisher`.
  - `cloudrun_ingestor/main.py`: imports **non-existent** `cloudrun_ingestor.event_utils`, `cloudrun_ingestor.schema_router`, `cloudrun_ingestor.config`, and uses `logging` without importing it.
- **Missing internal module**:
  - `backend.common.pubsub_publisher` is referenced but **does not exist** in this repo.
- **Additional high-signal finding (outside requested folders, but affects importability)**:
  - `backend/execution/engine.py` appears to have a **syntax error** (`unmatched ')'`) detected during import resolution from `tests/test_multi_asset_execution.py`.

## Confirmed active scripts (KEEP)

Strong evidence of active usage (service entrypoints and/or referenced by ops/docs/yaml/sh in-repo):
- **Service / runtime entrypoints (HIGH)**: `backend/app.py`, `backend/execution_agent/main.py`, `cloudrun_consumer/main.py`, `cloudrun_ingestor/main.py` (active intent but currently broken), `functions/main.py`.
- **CI / guardrails (HIGH)**: `scripts/ci/check_bash_vars.py`, `scripts/ci/check_ci_guardrail_enforcement.py`, `scripts/ci/check_no_latest_tags.py`, `scripts/ci/check_python_runtime_guardrails.py`, `scripts/ci/validate_yaml_syntax.py`.
- **Ops / verification tooling (MED→HIGH)**: `scripts/*smoke*`, `scripts/verify_*`, `scripts/validate_*`, plus `scripts/data_plane_smoke_test.py`.

## Suspected dead / manual-only / historical artifacts

### Highest confidence “dead/broken” (candidates for SAFE-TO-DELETE)
- `functions/ingest_alpaca.py` (**LOW**) — syntax error; no references detected.
- `backend/streams/alpaca_options_window_ingest.py` (**LOW→MED**) — 37-line stub; appears superseded by `backend/streams/alpaca_option_window_ingest.py` (full implementation).
- `backend/ingestion/pubsub_event_ingestion_service.py` (**MED**) — incomplete stub; not importable as-is.
- `scripts/ingest_market_data.py` (**MED**) — no `main()` and no `__main__` guard; looks like incomplete artifact.
- `zzz-utbot_atr_live_1M_Rev_F22.py` (**MED**) — standalone strategy file importing non-repo helpers (e.g., `ut_core_helper`); unreferenced.

### Likely manual/ad-hoc utilities (do NOT delete without confirmation)
Not referenced by other modules or scanned repo text, but contain real logic and may be run manually:
- `scripts/ledger_pnl_demo.py` (**MED**)
- `scripts/validate_alpaca_account.py` (**MED**)
- `scripts/place_test_order.py`, `scripts/insert_paper_order.py` (**MED**) — operator tools; depend on Alpaca SDK.
- `backend/ingestion/rate_limit.py` (**MED**) — useful utility but currently appears unused.
- `backend/ingestion/config.py` (**MED**) — compatibility constants module; may be unused depending on final Cloud Run ingestor wiring.

## SAFE-TO-DELETE list (no deletions performed)

**LOW**
- `functions/ingest_alpaca.py`
- `backend/streams/alpaca_options_window_ingest.py`

**MED**
- `backend/ingestion/pubsub_event_ingestion_service.py`
- `scripts/ingest_market_data.py`
- `zzz-utbot_atr_live_1M_Rev_F22.py`

## KEEP list (with purpose)

### `scripts/*.py`
- CI checks (`scripts/ci/*`), smoke/verification (`scripts/*smoke*`, `scripts/verify_*`, `scripts/validate_*`), data seeding/replay (`scripts/seed_*`, `scripts/replay_*`, `scripts/populate_*`), and strategy runners (`scripts/run_*`).

### `backend/streams/*.py`

| File | Main | Syntax | Logic | Imports | Refs | Delete risk |
|---|---:|---:|---|---|---:|---|
| `backend/streams/__init__.py` | N | OK | Minimal (package marker) | OK | N | HIGH |
| `backend/streams/alpaca_auth_smoke.py` | N | OK | OK | OK | N | MED |
| `backend/streams/alpaca_backfill_bars.py` | N | OK | OK | OK | N | MED |
| `backend/streams/alpaca_bars_ingest.py` | N | OK | OK | OK | Y | HIGH |
| `backend/streams/alpaca_env.py` | N | OK | OK | OK | N | HIGH |
| `backend/streams/alpaca_option_window_ingest.py` | Y | OK | OK | External deps: `psycopg`, `psycopg2` | N | HIGH |
| `backend/streams/alpaca_options_chain_ingest.py` | N | OK | OK | OK | Y | HIGH |
| `backend/streams/alpaca_options_window_ingest.py` | N | OK | **Stub** (37-line incomplete artifact) | OK | N | LOW→MED |
| `backend/streams/alpaca_order_smoke_test.py` | N | OK | OK | OK | N | MED |
| `backend/streams/alpaca_quotes_streamer.py` | N | OK | OK | OK | Y | HIGH |
| `backend/streams/alpaca_trade_candle_aggregator.py` | N | OK | OK | OK | Y | HIGH |
| `backend/streams/quotes_rest_runner.py` | N | OK | OK | OK | N | MED |
| `backend/streams/test_live_quote_ingest.py` | Y | OK | OK | External deps: `psycopg` | Y | MED |

### `backend/ingestion/*.py`

| File | Main | Syntax | Logic | Imports | Refs | Delete risk |
|---|---:|---:|---|---|---:|---|
| `backend/ingestion/__init__.py` | N | OK | Minimal (package marker) | OK | N | HIGH |
| `backend/ingestion/config.py` | N | OK | OK (compat constants) | OK | N | MED |
| `backend/ingestion/congressional_disclosures.py` | Y | OK | OK | External deps: `httpx`, `nats`, `pydantic` | Y | MED |
| `backend/ingestion/firebase_writer.py` | N | OK | OK | External deps: `google.api_core` / `google` | Y | HIGH |
| `backend/ingestion/ingest_heartbeat_handler.py` | N | OK | OK | External deps: `firebase_admin` | Y | HIGH |
| `backend/ingestion/market_data_ingest.py` | N | OK | OK | OK | Y | HIGH |
| `backend/ingestion/market_data_ingest_service.py` | N | OK | OK | External deps: `fastapi` | Y | HIGH |
| `backend/ingestion/publisher.py` | N | OK | OK | OK | N | MED |
| `backend/ingestion/pubsub_event_ingestion_service.py` | N | OK | **Stub** (file ends with placeholder comment); also uses `logging` without import | **Internal missing**: `backend.common.pubsub_publisher`; external deps: `google` | Y | MED |
| `backend/ingestion/pubsub_event_store.py` | N | OK | OK | **Internal missing**: `backend.common.pubsub_publisher`; external deps: `google`; also uses `logging` without import | Y | HIGH |
| `backend/ingestion/pubsub_push_validation.py` | N | OK | OK | External deps: `fastapi`, `starlette` | Y | HIGH |
| `backend/ingestion/rate_limit.py` | N | OK | OK (utility) | OK | N | MED |
| `backend/ingestion/smoke_check_market_data_ingest.py` | Y | OK | OK | OK | N | MED |
| `backend/ingestion/vm_ingest.py` | Y | OK | OK | External deps: `google` | N | MED |

### `cloudrun_ingestor/*.py`

| File | Main | Syntax | Logic | Imports | Refs | Delete risk |
|---|---:|---:|---|---|---:|---|
| `cloudrun_ingestor/__init__.py` | N | OK | Minimal (package marker) | OK | N | HIGH |
| `cloudrun_ingestor/gunicorn_conf.py` | N | OK | OK | OK | N | HIGH |
| `cloudrun_ingestor/main.py` | N | OK | OK (but currently broken) | **Internal missing**: `cloudrun_ingestor.event_utils`, `cloudrun_ingestor.schema_router`, `cloudrun_ingestor.config`; external deps: `google`; also uses `logging` without import | Y | HIGH |
| `cloudrun_ingestor/shutdown_smoke.py` | Y | OK | OK | OK | N | MED |

### `functions/*.py`

| File | Main | Syntax | Logic | Imports | Refs | Delete risk |
|---|---:|---:|---|---|---:|---|
| `functions/backtest_callable.py` | N | OK | OK | External deps: `firebase_admin`, `firebase_functions`; internal/path-dependent: `strategies.*` | Y | HIGH |
| `functions/backtester.py` | Y | OK | OK | External deps: `alpaca.data.*`; internal/path-dependent: `strategies.*` | Y | HIGH |
| `functions/base_strategy.py` | N | OK | OK (but has placeholder `pass` in `execute_trade`) | OK | N | MED |
| `functions/consensus_engine.py` | N | OK | OK | External deps: `firebase_admin`; internal/path-dependent: `strategies.*` | Y | HIGH |
| `functions/dashboard.py` | Y | OK | OK | External deps: `streamlit`, `pandas`, `plotly` | Y | MED |
| `functions/example_gex_usage.py` | Y | OK | OK | External deps: `alpaca_trade_api` | Y | MED |
| `functions/executor.py` | N | OK | OK | OK | Y | HIGH |
| `functions/gamma_scalper.py` | Y | OK | OK | External deps: `alpaca_trade_api`, `yfinance` | N | MED |
| `functions/health_check.py` | Y | OK | OK | External deps: `alpaca_trade_api`, `firebase_admin` | Y | HIGH |
| `functions/ingest_alpaca.py` | N | **FAIL** | **Broken** (syntax error) | External deps: `firebase_admin` | N | LOW |
| `functions/init_multitenant_db.py` | Y | OK | OK | External deps: `firebase_admin` | N | MED |
| `functions/journaling.py` | N | OK | OK | External deps: `vertexai`, `firebase_admin`, `firebase_functions` | Y | HIGH |
| `functions/kalman_filter.py` | Y | OK | OK | External deps: `yfinance` | N | MED |
| `functions/maestro_bridge.py` | Y | OK | OK | OK | Y | MED |
| `functions/main.py` | N | OK | OK | External deps: `alpaca_trade_api`, `firebase_admin`, `firebase_functions` | Y | HIGH |
| `functions/market_clock.py` | Y | OK | OK | OK | Y | MED |
| `functions/multi_agent_orchestrator.py` | Y | OK | OK | OK | N | MED |
| `functions/pairs_trader.py` | Y | OK | OK | External deps: `pandas`, `alpaca_trade_api` | N | MED |
| `functions/risk_manager.py` | N | OK | OK | External deps: `google.cloud` | Y | HIGH |
| `functions/risk_manager_example.py` | Y | OK | OK | OK | Y | MED |
| `functions/run_gemini_analysis.py` | Y | OK | OK | External deps: `google.cloud` | Y | MED |
| `functions/scheduled_vix_ingestion.py` | N | OK | OK | External deps: `firebase_admin`, `firebase_functions`, `alpaca_trade_api` | Y | HIGH |
| `functions/sentiment_analyzer.py` | Y | OK | OK | External deps: `alpaca_trade_api`, `transformers`, `torch` | N | MED |
| `functions/stress_test_runner.py` | N | OK | OK | External deps: `google.cloud` | Y | MED |
| `functions/test_gex_engine.py` | Y | OK | OK | OK | Y | MED |
| `functions/ticker_service.py` | Y | OK | OK | External deps: `alpaca_trade_api`, `firebase_admin` | Y | HIGH |
| `functions/ticker_service_example.py` | Y | OK | OK | External deps: `firebase_admin` | Y | MED |
| `functions/user_onboarding.py` | N | OK | OK | External deps: `firebase_admin`, `firebase_functions` | Y | HIGH |
| `functions/validate_whale_schema.py` | N | OK | OK | OK | N | MED |
| `functions/verify_pipeline_data.py` | Y | OK | OK | External deps: `firebase_admin` | N | MED |
| `functions/whale_consolidator.py` | Y | OK | OK | External deps: `alpaca_trade_api`, `firebase_admin` | N | MED |

## Appendix B — Additional `__main__` blocks (outside requested folders)

These files contain `if __name__ == \"__main__\":` but are outside the five requested entrypoint folders. They are included to satisfy “any `__main__` blocks” enumeration.

Notes:
- Many are **tests/examples**; presence of `__main__` does not imply production entrypoint.
- Import notes here are the same style as Appendix A (static resolution + obvious missing `logging` import checks).

| File | Syntax | Imports (notable) | Refs | Delete risk |
|---|---:|---|---:|---|
| `agenttrader/backend/strategies/delta_momentum_bot.py` | OK | External deps: `nats`; **internal mismatch**: imports `agenttrader.backend.utils.*` but repo path is `backend/utils/*` | Y | MED |
| `backend/analytics/example_integration.py` | OK | OK | Y | MED |
| `backend/app.py` | OK | External deps: `fastapi`, `uvicorn` | Y | HIGH |
| `backend/dependency_parity_check.py` | OK | OK | N | MED |
| `backend/execution_agent/main.py` | OK | OK | Y | HIGH |
| `backend/jobs/options_window.py` | OK | OK | N | HIGH |
| `backend/jobs/smoke_imports.py` | OK | OK | N | MED |
| `backend/messaging/examples/heartbeat_local_demo.py` | OK | OK | Y | MED |
| `backend/news_ingest/__main__.py` | OK | OK | N | MED |
| `backend/news_ingest/main.py` | OK | OK | N | MED |
| `backend/strategies/options_bot.py` | OK | External deps: `nats`, `pydantic` | Y | MED |
| `backend/strategy/naive_strategy_driver.py` | OK | External deps: `psycopg2` | N | MED |
| `backend/strategy_engine/driver.py` | OK | External deps: `pydantic` | Y | HIGH |
| `backend/strategy_engine/sentiment_strategy_driver.py` | OK | External deps: `pydantic` | Y | HIGH |
| `backend/strategy_engine/test_sentiment_strategy.py` | OK | OK | Y | MED |
| `backend/strategy_engine/test_strategy_local.py` | OK | OK | N | MED |
| `backend/strategy_runner/examples/gamma_scalper_0dte/smoke_test.py` | OK | OK | Y | MED |
| `backend/strategy_runner/examples/gamma_scalper_0dte/test_strategy.py` | OK | OK | Y | MED |
| `backend/strategy_runner/guest/guest_runner.py` | OK | OK | Y | MED |
| `backend/strategy_runner/harness.py` | OK | OK | Y | HIGH |
| `backend/strategy_service/scripts/insert_paper_order.py` | OK | External deps: `psycopg` | N | MED |
| `backend/streams_bridge/main.py` | OK | OK | Y | HIGH |
| `backend/streams_bridge/test_stream_bridge_local.py` | OK | OK | N | MED |
| `backend/streams_bridge/test_writer_smoke.py` | OK | OK | N | MED |
| `backend/tools/stream_dummy_market_data.py` | OK | External deps: `psycopg` | N | MED |
| `cloudrun_consumer/main.py` | OK | External deps: `fastapi`, `uvicorn`, `google.cloud` | Y | HIGH |
| `cloudrun_consumer/scripts/load_test_pubsub_push.py` | OK | OK | Y | MED |
| `cloudrun_consumer/tests/test_event_utils.py` | OK | OK | N | MED |
| `cloudrun_consumer/tests/test_lww.py` | OK | OK | N | MED |
| `cloudrun_consumer/tests/test_replay_idempotency.py` | OK | OK | N | MED |
| `cloudrun_consumer/tests/test_router.py` | OK | OK | N | MED |
| `cloudrun_consumer/tests/test_trade_signals_idempotency.py` | OK | OK | N | MED |
| `functions/strategies/example_maestro_integration.py` | OK | External deps: `firebase_admin` | Y | MED |
| `functions/strategies/example_maestro_usage.py` | OK | **Import path issue**: expects top-level `maestro_orchestrator` (exists at `functions/strategies/maestro_orchestrator.py`) | Y | MED |
| `functions/strategies/test_maestro_orchestrator.py` | OK | **Import path issue**: expects top-level `maestro_orchestrator` | Y | MED |
| `functions/strategies/test_sector_rotation.py` | OK | External deps: `pytest`; **import path issue**: expects top-level `sector_rotation` (exists at `functions/strategies/sector_rotation.py`) | Y | MED |
| `functions/strategies/verify_maestro_implementation.py` | OK | OK | Y | MED |
| `functions/strategies/verify_sector_rotation_loader.py` | OK | Internal/path-dependent: `strategies.loader` | Y | MED |
| `functions/utils/gex_calculator.py` | OK | External deps: `firebase_admin` | Y | MED |
| `main.py` | OK | OK (print-only, buildpack detection) | Y | HIGH |
| `research/promotion/promote_to_strategy_config.py` | OK | OK | Y | MED |
| `scripts/ci/check_bash_vars.py` | OK | OK | Y | HIGH |
| `scripts/ci/check_ci_guardrail_enforcement.py` | OK | OK | N | HIGH |
| `scripts/ci/check_no_latest_tags.py` | OK | OK | Y | HIGH |
| `scripts/ci/check_python_runtime_guardrails.py` | OK | OK | Y | HIGH |
| `scripts/ci/validate_yaml_syntax.py` | OK | OK | Y | HIGH |
| `tests/test_backtester.py` | OK | External deps: `pytest`; internal/path-dependent: `strategies.*` | Y | MED |
| `tests/test_base_strategy.py` | OK | External deps: `pytest`; internal/path-dependent: `strategies.base` | Y | MED |
| `tests/test_circuit_breakers.py` | OK | External deps: `pytest` | Y | MED |
| `tests/test_congressional_alpha_strategy.py` | OK | External deps: `pytest` | Y | MED |
| `tests/test_consensus_engine.py` | OK | External deps: `pytest`; internal/path-dependent: `strategies.*` | Y | MED |
| `tests/test_deployment.py` | OK | OK | N | MED |
| `tests/test_gamma_scalper_strategy.py` | OK | External deps: `pytest` | Y | MED |
| `tests/test_maestro_orchestration.py` | OK | External deps: `pytest` | Y | MED |
| `tests/test_multi_asset_execution.py` | OK | External deps: `pytest`; **also triggers syntax error** in `backend/execution/engine.py` during import | Y | MED |
| `tests/test_rate_limiting.py` | OK | Internal/path-dependent: `strategies.loader` | Y | MED |
| `tests/test_watchdog.py` | OK | External deps: `pytest` | Y | MED |
| `zzz-utbot_atr_live_1M_Rev_F22.py` | OK | External deps: `pandas`, `ta`, `alpaca.*`; internal missing: `ut_core_helper` and other non-repo helpers | N | MED |

- Alpaca streaming/ingestion utilities (bars/quotes/candles/options) and smoke tests.

### `backend/ingestion/*.py`
- Ingestion services/utilities (Pub/Sub validation, heartbeat handler, market ingest service, Firestore writer, etc.). Note the incomplete `pubsub_event_ingestion_service.py`.

### `cloudrun_ingestor/*.py`
- Cloud Run ingestor service entrypoint and related runtime configuration files. Note current missing modules under `cloudrun_ingestor/`.

### `functions/*.py`
- Firebase Functions entrypoints/orchestration + strategy/runtime modules (often require external deps like Firebase Admin, Alpaca, ML libs).

## Appendix A — Per-file verification (requested entrypoints)

The per-file inventory is included below, grouped by folder, with:
- **Non-empty**: all entries are non-empty unless explicitly stated otherwise (none were empty).
- **Syntax**: OK / FAIL
- **Logic**: OK / minimal / stub
- **Imports**: OK / external deps required / internal missing / guaranteed runtime failure
- **Refs**: whether the file path appears in repo text (docs/yaml/sh) during scan

### `scripts/*.py`

| File | Main | Syntax | Logic | Imports | Refs | Delete risk |
|---|---:|---:|---|---|---:|---|
| `scripts/agent_executor.py` | Y | OK | OK | OK | N | MED |
| `scripts/calc_monthly_performance_fees.py` | Y | OK | OK | External deps: `google.cloud` | N | MED |
| `scripts/calc_monthly_strategy_perf_snapshot.py` | Y | OK | OK | OK | N | MED |
| `scripts/data_plane_smoke_test.py` | Y | OK | OK | External deps: `google.cloud` | Y | HIGH |
| `scripts/demo_whale_flow_service.py` | Y | OK | OK | OK | Y | MED |
| `scripts/emit_chaos_pubsub_events.py` | Y | OK | OK | OK | Y | MED |
| `scripts/generate_blueprint.py` | Y | OK | OK | OK | Y | MED |
| `scripts/import_runtime_modules.py` | Y | OK | OK | OK | N | MED |
| `scripts/ingest_market_data.py` | N | OK | **Stub** (no `main` / no `__main__`) | OK | N | MED |
| `scripts/init_shadow_mode_config.py` | Y | OK | OK | External deps: `google.cloud` | Y | MED |
| `scripts/insert_paper_order.py` | Y | OK | OK | External deps: `alpaca.*` | N | MED |
| `scripts/ledger_pnl_demo.py` | Y | OK | OK | OK | N | MED |
| `scripts/mock_market_feed.py` | Y | OK | OK | External deps: `pydantic`, `nats` | N | MED |
| `scripts/mock_options_feed.py` | Y | OK | OK | OK | N | MED |
| `scripts/place_test_order.py` | N | OK | OK | External deps: `alpaca.*` | N | MED |
| `scripts/populate_institutional_features_data.py` | Y | OK | OK | External deps: `firebase_admin` | Y | MED |
| `scripts/populate_whale_flow_test_data.py` | Y | OK | OK | External deps: `firebase_admin`, `google.cloud.firestore_v1` | Y | MED |
| `scripts/replay_from_logs.py` | Y | OK | OK | OK | Y | MED |
| `scripts/replay_ticks_to_candles.py` | Y | OK | OK | OK | Y | MED |
| `scripts/report_v2_deploy.py` | N | OK | OK | OK | Y | MED |
| `scripts/run_backtest_example.py` | Y | OK | OK | Internal/path-dependent: `strategies.gamma_scalper` | Y | MED |
| `scripts/run_experiment.py` | Y | OK | OK | OK | Y | MED |
| `scripts/run_sector_rotation_strategy.py` | Y | OK | OK | External deps: `firebase_admin`; internal/path-dependent: `strategies.sector_rotation` | Y | MED |
| `scripts/run_stress_test.py` | Y | OK | OK | OK | Y | MED |
| `scripts/seed_sentiment_data.py` | Y | OK | OK | External deps: `firebase_admin` | Y | MED |
| `scripts/seed_whale_flow_data.py` | Y | OK | OK | External deps: `google.cloud` | Y | MED |
| `scripts/smoke_check_imports.py` | Y | OK | OK | OK | Y | HIGH |
| `scripts/test_ai_trade_analysis.py` | Y | OK | OK | External deps: `google.cloud` | Y | MED |
| `scripts/test_macro_scraper.py` | Y | OK | OK | OK | Y | MED |
| `scripts/test_trade_executor.py` | Y | OK | OK | OK | Y | MED |
| `scripts/update_execution_board.py` | Y | OK | OK | OK | Y | MED |
| `scripts/validate_alpaca_account.py` | Y | OK | OK | OK | N | MED |
| `scripts/validate_intent_logging.py` | Y | OK | OK | OK | Y | HIGH |
| `scripts/verify_risk_management.py` | Y | OK | OK | OK | Y | HIGH |
| `scripts/verify_zero_trust.py` | Y | OK | OK | External deps: `firebase_admin`, `nacl.signing`; internal/path-dependent: `strategies.loader` | Y | HIGH |

### `backend/streams/*.py`

