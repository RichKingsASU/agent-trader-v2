# AgentTrader v2 — Repo Blueprint

**repo_id**: `RichKingsASU/agent-trader-v2`
**git_sha**: `a4715d6bfe9eba0d1f7aeadb23a13da7d77542e0`
**generated_at_utc**: `2026-01-13T16:57:16Z`

## Executive Snapshot (what v2 is + safety posture)

AgentTrader v2 is a multi-component trading platform with explicit **safety-first defaults**. This blueprint is generated directly from repo artifacts (k8s manifests, backend modules, and docs) and intentionally reports **unknown** when it cannot detect something deterministically.

- **Trading enabled by this blueprint**: **No** (documentation-only; does not execute trades).
- **External services required to generate**: **No** (local file scan only).
- **Safety posture**: kill-switch-first, dry-run oriented, and identity/intent documentation present.

### Inferred logical subsystems (from `backend/` layout)

- **mission-control**: `backend/app.py`, `backend/messaging`, `backend/risk`, `backend/risk_service`, `backend/tenancy`
- **marketdata**: `backend/ingestion`, `backend/marketdata`
- **strategy**: `backend/strategy_engine`, `backend/strategy_runner`, `backend/strategy_service`
- **execution**: `backend/execution`, `backend/services/execution_service`

## Component Inventory (table)

| component name | kind (deploy/sts/job) | image | AGENT_ROLE / AGENT_MODE default | health endpoints (if found) |
|---|---|---|---|---|
| execution-agent | deploy | execution-agent:REPLACE_ME | AGENT_ROLE=execution; AGENT_MODE=OFF | unknown |
| agenttrader-ops-ui | deploy | ghcr.io/richkingsasu/agenttrader-ops-ui@sha256:REPLACE_ME | AGENT_ROLE=unknown; AGENT_MODE=unknown | liveness: http GET / port http; readiness: http GET / port http |
| daily-dr-snapshots | cronjob | REPLACE_WITH_YOUR_OPS_IMAGE@sha256:REPLACE_ME | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |
| execution-engine | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/execution-engine:54afffe | AGENT_ROLE=unknown; AGENT_MODE=OFF | liveness: http GET /healthz port http; readiness: http GET /healthz port http |
| gamma-strategy | sts | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:54afffe | AGENT_ROLE=strategy_eval; AGENT_MODE=EVAL | liveness: http GET /healthz port http; readiness: http GET /readyz port http; startup: http GET /healthz port http |
| marketdata-mcp-server | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata-mcp-server:54afffe | AGENT_ROLE=marketdata; AGENT_MODE=OBSERVE | liveness: http GET /healthz port http; readiness: http GET /readyz port http; startup: http GET /healthz port http |
| mission-control | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/mission-control:REPLACE_ME | AGENT_ROLE=unknown; AGENT_MODE=OBSERVE | liveness: http GET /healthz port 8080; readiness: http GET /healthz port 8080 |
| ops-heartbeat-writer | cronjob | bitnami/kubectl:1.29.0 | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |
| ops-post-market | cronjob | bitnami/kubectl:1.29.0 | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |
| strategy-engine | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:54afffe | AGENT_ROLE=unknown; AGENT_MODE=OFF | liveness: http GET /healthz port http; readiness: http GET /readyz port http; startup: http GET /healthz port http |
| strategy-engine | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-engine:54afffe | AGENT_ROLE=unknown; AGENT_MODE=unknown | liveness: http GET /healthz port http; readiness: http GET /readyz port http; startup: http GET /healthz port http |
| whale-strategy | sts | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:54afffe | AGENT_ROLE=strategy_eval; AGENT_MODE=EVAL | liveness: http GET /healthz port http; readiness: http GET /readyz port http; startup: http GET /healthz port http |

### Discovered Services (topology context)

| service | namespace | ports | manifest |
|---|---|---|---|
| `agenttrader-execution-agent` | `trading-floor` | `80->http` | `k8s/26-execution-engine-deployment-and-service.yaml` |
| `agenttrader-gamma-strategy` | `trading-floor` | `80->http` | `k8s/12-strategy-runtime-services.yaml` |
| `agenttrader-marketdata-mcp-server` | `trading-floor` | `80->http` | `k8s/20-marketdata-mcp-server-deployment-and-service.yaml` |
| `agenttrader-ops-ui` | `trading-floor` | `80->http` | `k8s/ops-ui/service.yaml` |
| `agenttrader-strategy-engine` | `trading-floor` | `80->http` | `k8s/25-strategy-engine-deployment-and-service.yaml` |
| `agenttrader-whale-strategy` | `trading-floor` | `80->http` | `k8s/12-strategy-runtime-services.yaml` |
| `marketdata-mcp-server` | `trading-floor` | `80->8080` | `k8s/20-marketdata-mcp-server-deployment-and-service.yaml` |
| `mission-control` | `trading-floor` | `80->8080` | `k8s/mission-control/service.yaml` |
| `strategy-engine` | `trading-floor` | `80->8080` | `k8s/30-strategy-engine-deployment-and-service.yaml` |

## Build Pipelines (table)

| cloudbuild file | image output |
|---|---|
| cloudbuild.congressional-ingest.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/congressional-ingest:${SHORT_SHA} |
| cloudbuild.marketdata.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata:$SHORT_SHA |
| cloudbuild.mcp.yaml | ${_REGION}-docker.pkg.dev/${_PROJECT}/${_REPO}/marketdata-mcp-server:${_TAG} |
| cloudbuild.strategy-engine.yaml | ${_REGION}-docker.pkg.dev/${_PROJECT}/${_REPO}/strategy-engine:${_TAG} |
| cloudbuild.strategy-gamma.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-gamma:${SHORT_SHA} |
| cloudbuild.strategy-runtime.yaml | ${_REGION}-docker.pkg.dev/${_PROJECT}/${_REPO}/strategy-runtime:${_TAG} |
| cloudbuild.strategy-whale.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-whale:${SHORT_SHA} |
| cloudbuild.strategy.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:$SHORT_SHA |
| cloudbuild.yaml | unknown |
| cloudrun_ingestor/cloudbuild.yaml | ${_IMAGE_TAG} |
| infra/cloudbuild_congressional_ingest.yaml | gcr.io/$PROJECT_ID/congressional-ingest:$SHORT_SHA |
| infra/cloudbuild_ingest.yaml | gcr.io/$PROJECT_ID/agenttrader-alpaca-ingest:$SHORT_SHA |
| infra/cloudbuild_options_ingest.yaml | gcr.io/$PROJECT_ID/agenttrader-options-ingest:$SHORT_SHA |
| infra/cloudbuild_pubsub_event_ingestion.yaml | gcr.io/$PROJECT_ID/agenttrader-pubsub-event-ingestion:$SHORT_SHA |
| infra/cloudbuild_strategy_engine.yaml | gcr.io/$PROJECT_ID/${_JOB_NAME}:$SHORT_SHA |
| infra/cloudbuild_stream_bridge.yaml | gcr.io/$PROJECT_ID/agenttrader-stream-bridge:$SHORT_SHA |

## Safety Controls

- **Kill-switch**: present (k8s manifests wire EXECUTION_HALTED via ConfigMap) (see `docs/KILL_SWITCH.md`, `k8s/05-kill-switch-configmap.yaml`).
- **Marketdata freshness gating**: present (backend/execution/marketdata_health.py: heartbeat staleness check).
- **Agent identity + intent logging**: documented (see `docs/ZERO_TRUST_AGENT_IDENTITY.md`; generator does not infer runtime settings).

## Ops Commands

### deploy

```bash
./scripts/deploy_v2.sh
```

### report

```bash
./scripts/report_v2_deploy.sh
```

### readiness

```bash
kubectl -n agenttrader get pods
kubectl -n agenttrader get deploy,sts,job,cronjob
```

### logs

```bash
kubectl -n agenttrader rollout status deploy/execution-agent
```
```bash
kubectl -n trading-floor rollout status deploy/agenttrader-ops-ui
```
```bash
kubectl -n trading-floor rollout status deploy/execution-engine
```
```bash
kubectl -n trading-floor rollout status sts/gamma-strategy
```
```bash
kubectl -n trading-floor rollout status deploy/marketdata-mcp-server
```
```bash
kubectl -n trading-floor rollout status deploy/mission-control
```
```bash
kubectl -n trading-floor rollout status deploy/strategy-engine
```
```bash
kubectl -n trading-floor rollout status deploy/strategy-engine
```
```bash
kubectl -n trading-floor rollout status sts/whale-strategy
```
```bash
kubectl -n agenttrader logs -l app.kubernetes.io/instance=execution-agent --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=agenttrader-ops-ui --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=daily-dr-snapshots --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=execution-engine --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=gamma-strategy --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=marketdata-mcp-server --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=mission-control --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=ops-heartbeat-writer --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=ops-post-market --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=strategy-engine --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=strategy-engine --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=whale-strategy --tail=200
```

## Known Gaps (automatically inferred)

- agenttrader/execution-agent: missing EXECUTION_HALTED kill-switch wiring
- agenttrader/execution-agent: missing probes (readiness/liveness)
- trading-floor/agenttrader-ops-ui: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/agenttrader-ops-ui: missing EXECUTION_HALTED kill-switch wiring
- trading-floor/daily-dr-snapshots: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/daily-dr-snapshots: missing EXECUTION_HALTED kill-switch wiring
- trading-floor/daily-dr-snapshots: missing probes (readiness/liveness)
- trading-floor/mission-control: missing EXECUTION_HALTED kill-switch wiring
- trading-floor/ops-heartbeat-writer: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/ops-heartbeat-writer: missing EXECUTION_HALTED kill-switch wiring
- trading-floor/ops-heartbeat-writer: missing probes (readiness/liveness)
- trading-floor/ops-post-market: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/ops-post-market: missing EXECUTION_HALTED kill-switch wiring
- trading-floor/ops-post-market: missing probes (readiness/liveness)
- trading-floor/strategy-engine: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/strategy-engine: missing EXECUTION_HALTED kill-switch wiring

## Links (docs index)

- `docs/AI_SIGNAL_INTEGRATION.md`
- `docs/AI_TRADE_ANALYSIS.md`
- `docs/BLUEPRINT.md`
- `docs/CANONICAL_ENV_VAR_CONTRACT.md`
- `docs/CIRCUIT_BREAKERS_IMPLEMENTATION.md`
- `docs/CIRCUIT_BREAKERS_INTEGRATION_EXAMPLE.md`
- `docs/CIRCUIT_BREAKERS_SUMMARY.md`
- `docs/CI_CONTRACT.md`
- `docs/CONFIG_SECRETS.md`
- `docs/CONGRESSIONAL_ALPHA_QUICKSTART.md`
- `docs/CONGRESSIONAL_ALPHA_STRATEGY.md`
- `docs/CONSENSUS_ENGINE.md`
- `docs/DEPLOYMENT_REPORT.md`
- `docs/DEPLOY_GCP.md`
- `docs/EXECUTION_AGENT_STATE_MACHINE.md`
- `docs/EXECUTION_ENGINE.md`
- `docs/FAULT_CONTAINMENT_TRADE_EXECUTION.md`
- `docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md`
- `docs/INSTITUTIONAL_ANALYTICS_DASHBOARD.md`
- `docs/KILL_SWITCH.md`
- `docs/LIVE_QUOTES_FLOW.md`
- `docs/LLM_SENTIMENT_IMPLEMENTATION_SUMMARY.md`
- `docs/LLM_SENTIMENT_STRATEGY_QUICKSTART.md`
- `docs/MARKETDATA_HEALTH_CONTRACT.md`
- `docs/MARKETPLACE_FLOW.md`
- `docs/MARKETPLACE_SCHEMA.md`
- `docs/MESSAGING.md`
- `docs/PNL_ATTRIBUTION.md`
- `docs/PROD_READINESS_CHECKLIST.md`
- `docs/REPLAY_LOG_SCHEMA.md`
- `docs/RISK_MANAGEMENT_KILLSWITCH.md`
- `docs/RISK_MANAGEMENT_QUICK_START.md`
- `docs/SAFE_SHUTDOWN.md`
- `docs/SECURITY_SANDBOX.md`
- `docs/SHADOW_MODE.md`
- `docs/SHADOW_MODE_QUICK_REFERENCE.md`
- `docs/SHADOW_PNL_TRACKING_GUIDE.md`
- `docs/STARTUP_CONFIG_CHECKLIST.md`
- `docs/STRATEGY_ARCHITECTURE.md`
- `docs/STRUCTURED_LOGGING_STANDARD.md`
- `docs/WHALE_FLOW_TRACKER.md`
- `docs/ZERO_TRUST_AGENT_IDENTITY.md`
- `docs/agent_charter.md`
- `docs/agents.md`
- `docs/agenttrader_blueprint.md`
- `docs/alerts_v1.md`
- `docs/alpaca_todo.md`
- `docs/ci_guardrails_v3.md`
- `docs/ci_ownership.md`
- `docs/consumer_idempotency.md`
- `docs/consumer_safety_check.md`
- `docs/consumer_topic_coverage.md`
- `docs/contract_alignment_plan.md`
- `docs/contracts/data_freshness.md`
- `docs/contracts_unification_plan.md`
- `docs/credentials.md`
- `docs/dataplane/README.md`
- `docs/dataplane/partitioning.md`
- `docs/dlq_and_retries.md`
- `docs/event_bus.md`
- `docs/event_contract_v1.md`
- `docs/feature_flags.md`
- `docs/firestore_indexes.md`
- `docs/firestore_write_profile.md`
- `docs/logging_alerts_v1.md`
- `docs/logging_schema.md`
- `docs/marketdata/candles.md`
- `docs/metrics_map.md`
- `docs/multi-tenant-api-reference.md`
- `docs/observability/logging.md`
- `docs/ops/README.md`
- `docs/ops/agent_mesh.md`
- `docs/ops/audit_pack.md`
- `docs/ops/day1_ops.md`
- `docs/ops/deploy_guardrails.md`
- `docs/ops/disaster_recovery.md`
- `docs/ops/dr_plan.md`
- `docs/ops/execution_board.md`
- `docs/ops/firebase_ops_dashboard_deploy.md`
- `docs/ops/go_no_go.md`
- `docs/ops/local_dev_connectivity_standard.md`
- `docs/ops/make_workflow.md`
- `docs/ops/mission_control.md`
- `docs/ops/ops_ui.md`
- `docs/ops/reporting.md`
- `docs/ops/runbooks/crashloop.md`
- `docs/ops/runbooks/crashloop_backoff.md`
- `docs/ops/runbooks/image_pull_backoff.md`
- `docs/ops/runbooks/marketdata_stale.md`
- `docs/ops/runbooks/post_market.md`
- `docs/ops/runbooks/pre_market.md`
- `docs/ops/runbooks/resource_pressure.md`
- `docs/ops/runbooks/strategy_engine_halted.md`
- `docs/ops/service_discovery.md`
- `docs/ops/slo.md`
- `docs/ops/status_contract.md`
- `docs/repo_cleanup_plan.md`
- `docs/runbooks/heartbeat.md`
- `docs/strategies/registry.md`
- `docs/stream_bridge_architecture.md`
- `docs/time/nyse_time.md`
- `docs/trading/execution_agent.md`
- `docs/trading/order_proposals.md`
- `docs/vnext_roadmap.md`
