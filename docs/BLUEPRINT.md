# AgentTrader v2 — Repo Blueprint

**repo_id**: `RichKingsASU/agent-trader-v2`
**git_sha**: `37e0c07175f9cb31e1e4d01acef2387d5e313647`
**generated_at_utc**: `2026-01-07T01:13:57Z`

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
| gamma-strategy | sts | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:54afffe | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |
| marketdata-mcp-server | deploy | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata-mcp-server:54afffe | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |
| whale-strategy | sts | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:54afffe | AGENT_ROLE=unknown; AGENT_MODE=unknown | unknown |

### Discovered Services (topology context)

| service | namespace | ports | manifest |
|---|---|---|---|
| `marketdata-mcp-server` | `trading-floor` | `80->8080` | `k8s/20-marketdata-mcp-server-deployment-and-service.yaml` |

## Build Pipelines (table)

| cloudbuild file | image output |
|---|---|
| cloudbuild.congressional-ingest.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/congressional-ingest:${SHORT_SHA}, us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/congressional-ingest:latest |
| cloudbuild.marketdata.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata:$SHORT_SHA |
| cloudbuild.mcp.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata-mcp-server:$SHORT_SHA |
| cloudbuild.strategy-engine.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-engine:${SHORT_SHA}, us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-engine:latest |
| cloudbuild.strategy-gamma.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-gamma:${SHORT_SHA}, us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-gamma:latest |
| cloudbuild.strategy-runtime.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:${SHORT_SHA}, us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:latest |
| cloudbuild.strategy-whale.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-whale:${SHORT_SHA}, us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-whale:latest |
| cloudbuild.strategy.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:$SHORT_SHA |
| cloudbuild.yaml | us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/marketdata-mcp-server:$SHORT_SHA |
| infra/cloudbuild_congressional_ingest.yaml | gcr.io/$PROJECT_ID/congressional-ingest:$SHORT_SHA |
| infra/cloudbuild_ingest.yaml | gcr.io/$PROJECT_ID/agenttrader-alpaca-ingest:$SHORT_SHA |
| infra/cloudbuild_options_ingest.yaml | gcr.io/$PROJECT_ID/agenttrader-options-ingest:$SHORT_SHA |
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
kubectl -n trading-floor get pods
kubectl -n trading-floor get deploy,sts,job,cronjob
```

### logs

```bash
kubectl -n trading-floor rollout status sts/gamma-strategy
```
```bash
kubectl -n trading-floor rollout status deploy/marketdata-mcp-server
```
```bash
kubectl -n trading-floor rollout status sts/whale-strategy
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=gamma-strategy --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=marketdata-mcp-server --tail=200
```
```bash
kubectl -n trading-floor logs -l app.kubernetes.io/instance=whale-strategy --tail=200
```

## Known Gaps (automatically inferred)

- cloudbuild.congressional-ingest.yaml: build pipeline references :latest (us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/congressional-ingest:latest)
- cloudbuild.strategy-engine.yaml: build pipeline references :latest (us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-engine:latest)
- cloudbuild.strategy-gamma.yaml: build pipeline references :latest (us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-gamma:latest)
- cloudbuild.strategy-runtime.yaml: build pipeline references :latest (us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-runtime:latest)
- cloudbuild.strategy-whale.yaml: build pipeline references :latest (us-east4-docker.pkg.dev/agenttrader-prod/trader-repo/strategy-whale:latest)
- trading-floor/gamma-strategy: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/gamma-strategy: missing probes (readiness/liveness)
- trading-floor/marketdata-mcp-server: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/marketdata-mcp-server: missing probes (readiness/liveness)
- trading-floor/whale-strategy: missing AGENT_ROLE/AGENT_MODE env defaults
- trading-floor/whale-strategy: missing probes (readiness/liveness)

## Links (docs index)

- `docs/AI_SIGNAL_INTEGRATION.md`
- `docs/AI_TRADE_ANALYSIS.md`
- `docs/BLUEPRINT.md`
- `docs/CIRCUIT_BREAKERS_IMPLEMENTATION.md`
- `docs/CIRCUIT_BREAKERS_INTEGRATION_EXAMPLE.md`
- `docs/CIRCUIT_BREAKERS_SUMMARY.md`
- `docs/CONGRESSIONAL_ALPHA_QUICKSTART.md`
- `docs/CONGRESSIONAL_ALPHA_STRATEGY.md`
- `docs/CONSENSUS_ENGINE.md`
- `docs/DEPLOYMENT_REPORT.md`
- `docs/DEPLOY_GCP.md`
- `docs/EXECUTION_AGENT_STATE_MACHINE.md`
- `docs/EXECUTION_ENGINE.md`
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
- `docs/SECURITY_SANDBOX.md`
- `docs/SHADOW_MODE.md`
- `docs/SHADOW_MODE_QUICK_REFERENCE.md`
- `docs/SHADOW_PNL_TRACKING_GUIDE.md`
- `docs/STRATEGY_ARCHITECTURE.md`
- `docs/WHALE_FLOW_TRACKER.md`
- `docs/ZERO_TRUST_AGENT_IDENTITY.md`
- `docs/agent_charter.md`
- `docs/agents.md`
- `docs/agenttrader_blueprint.md`
- `docs/alpaca_todo.md`
- `docs/credentials.md`
- `docs/event_bus.md`
- `docs/feature_flags.md`
- `docs/multi-tenant-api-reference.md`
- `docs/ops/README.md`
- `docs/ops/reporting.md`
- `docs/stream_bridge_architecture.md`
- `docs/trading/order_proposals.md`
