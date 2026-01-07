# AgentTrader v2 — Agent Mesh Operational Plan (Single Source of Truth)

**Status**: draft (ops-facing)  
**Scope**: autonomy-safe operations for AgentTrader v2 workloads (Kubernetes + Cloud Run)  
**Absolute safety rule**: this plan **does not enable trading execution**. The `execution-agent` remains **OFF / scaled-to-zero** unless a human explicitly performs a controlled change outside these runbooks.

## Purpose

The “agent mesh” is the set of services/jobs that collectively ingest market signals, run strategies, produce *order proposals*, and (optionally) execute orders. This document defines:

- **Roster** (what agents exist)
- **Responsibilities and contracts** (what each agent must do / must never do)
- **Cadence** (what should happen pre-market, intraday, and post-market)
- **Failure modes + runbooks** (how to respond safely and predictably)
- **Escalation rules** (when to page humans / stop the line)

## Safety invariants (non-negotiable)

- **No execution enabling**: do not scale up or activate `execution-agent` from any automated process.
- **Kill-switch respected**: `EXECUTION_HALTED=1` (default in k8s) halts all broker-side execution. See `docs/KILL_SWITCH.md`.
- **Marketdata freshness gating**: strategies and execution must treat stale/unreachable marketdata health as **hard-stop**. See `docs/MARKETDATA_HEALTH_CONTRACT.md`.
- **Read-only ops**: ops scripts in `scripts/ops_*.sh` are **read-only** (no writes to cluster, no mode flips).

## Agent roster (table)

| agent_name | role | mode default | inputs (topics/endpoints/files) | outputs (topics/endpoints/files) | criticality | owner | restart policy + probes | SLO target |
|---|---|---|---|---|---|---|---|---|
| `marketdata-mcp-server` | Live marketdata streamer + MCP / heartbeat | **OBSERVE** (`DRY_RUN=1`) | Alpaca creds (mounted), `/etc/agenttrader/kill-switch/EXECUTION_HALTED` (read), quote stream | `GET /healthz` heartbeat, `GET /health`, internal tick snapshot | **P0** | unassigned | k8s Deployment; liveness/readiness via HTTP `:8080/healthz` recommended | **99.9%** heartbeat availability during market hours |
| `market-ingest-service` | Market ingestion background worker (Cloud Run) | **OBSERVE** | broker feed, config env, Firestore (heartbeat write) | `GET /health`, Firestore heartbeat docs | **P0** | unassigned | Cloud Run restart on crash; probe `GET /health` | **99.9%** health endpoint availability |
| `strategy-engine` (runtime: `gamma-strategy`, `whale-strategy`) | Strategy runtime producing **order proposals** only | **OBSERVE** | `MARKETDATA_HEALTH_URL` (`/healthz`), kill-switch file (read), market/analytics stores | proposal events (logs/DB), strategy metrics | **P1** | unassigned | k8s StatefulSet; probe (if HTTP exposed) `GET /health` recommended | **99.5%** availability during market hours |
| `strategy-service` | Strategy management API (CRUD + analytics) | **OBSERVE** | DB/Firestore, kill-switch state (read) | REST API routes, paper orders, analytics | **P1** | unassigned | API service; probe **(missing today)** `GET /health` recommended | **99.5%** monthly |
| `execution-agent` (`execution-engine`) | Broker execution API (must be disabled) | **OFF** (**disabled/scaled 0**) | order intents, kill-switch, marketdata heartbeat | broker orders (ONLY when enabled) | **P0** when enabled | unassigned | probe `GET /health`, gating via `GET /state` | **99.9%** when enabled (not applicable while OFF) |
| `mission-control` (ops aggregator) | Ops “single pane”: collect health, summarize posture | **OFF** (manual) | deploy report, health endpoints, cluster signals | `audit_artifacts/ops_runs/*`, alerts (future) | **P1** | unassigned | batch job; exit 0 on success | N/A |
| `reporting-agent` (deploy report) | Deterministic deployment/health report | **OBSERVE** (manual) | `kubectl` context + namespace | `audit_artifacts/deploy_report.md/.json` | **P1** | unassigned | script-only; no probes | N/A |
| `research-runner` (optional) | Offline research / backtests | **OFF** | historical data, notebooks, local configs | artifacts in `audit_artifacts/` | **P3** | unassigned | manual job | N/A |
| `congressional-ingest` (if used) | External “congressional disclosures” ingest | **OBSERVE** | Quiver API, NATS, tenant config | NATS events, persisted disclosures | **P2** | unassigned | Cloud Run service; restart on crash | **99.0%** (business hours) |

> Notes
> - `execution-agent` is intentionally listed but must remain OFF by default. See “Escalation rules” for enabling procedure (human-only).
> - `strategy-engine` exists as both Cloud Run Job patterns (see `scripts/setup_cloud_run_strategy_engine.sh`) and k8s StatefulSets (`k8s/10-gamma-strategy-statefulset.yaml`, `k8s/11-whale-strategy-statefulset.yaml`).

---

## Agent contracts (responsibilities + explicit “never” rules)

### `marketdata-mcp-server`

- **Must do**
  - Maintain live quote stream ingestion and update local tick snapshot.
  - Serve `GET /healthz` heartbeat per `docs/MARKETDATA_HEALTH_CONTRACT.md`.
  - Log kill-switch state at startup (visibility only; non-execution service).
- **Must never do**
  - Place broker orders or emit execution intents.
  - Treat stale marketdata as “ok”; heartbeat must return **503** when stale.
- **Health contract endpoints**
  - **`GET /healthz`**: returns **200** only when ticks are fresh; **503** otherwise.
  - **`GET /health`**: process-level health.
- **Safety dependencies**
  - Correctly mounted kill-switch file (read-only): `/etc/agenttrader/kill-switch/EXECUTION_HALTED`.
  - Broker credentials must be mounted via secrets; never committed.

### `market-ingest-service` (Cloud Run)

- **Must do**
  - Ingest market data and write a heartbeat that downstream agents can validate.
  - Serve `GET /health` continuously (Cloud Run requirement).
- **Must never do**
  - Place broker orders.
  - Continue producing “fresh” heartbeat when upstream feed is broken.
- **Health contract endpoints**
  - **`GET /health`**: includes basic stats (see `backend/ingestion/market_data_ingest_service.py`).
- **Safety dependencies**
  - Marketdata source credentials.
  - Firestore permissions (write heartbeat only; principle of least privilege).

### `strategy-engine` (runtime workloads)

- **Must do**
  - Refuse to run if marketdata heartbeat is stale/unreachable.
  - Produce **order proposals** (not executions) and record reasoning/audit metadata.
  - Treat kill-switch as “halt posture” (visibility + do not escalate to execution).
- **Must never do**
  - Call broker APIs directly.
  - Attempt to bypass kill-switch or marketdata gating.
- **Health contract endpoints**
  - If HTTP server is present: **recommend** `GET /health` and optionally `GET /metrics`.
  - If no HTTP server: rely on platform health (pod Running + no CrashLoop) and log heartbeat checks.
- **Safety dependencies**
  - `MARKETDATA_HEALTH_URL` + `MARKETDATA_MAX_AGE_SECONDS` (or equivalent).
  - Kill-switch file mounted read-only.

### `strategy-service`

- **Must do**
  - Serve strategy management endpoints reliably (CRUD + analytics).
  - Surface kill-switch active status in logs (visibility).
- **Must never do**
  - Execute live orders.
  - Accept “live trading” requests that bypass execution gating.
- **Health contract endpoints**
  - **Recommended**: add `GET /health` in the service (currently not defined).
- **Safety dependencies**
  - Database/Firestore read/write permissions scoped to strategy metadata and paper-order records.

### `execution-agent` / `execution-engine` (DISABLED by default)

- **Must do (when enabled by humans)**
  - Enforce state machine gating: **READY + LIVE + kill-switch off** before broker routing.
  - Enforce marketdata freshness gate (stale ⇒ refuse).
  - Expose `/state` for operational inspection.
- **Must never do**
  - Execute orders when `EXECUTION_HALTED=1`.
  - Execute orders when marketdata is stale/unreachable.
  - Execute orders in any default / unattended scenario (must be human-enabled).
- **Health contract endpoints**
  - **`GET /health`**: process-level.
  - **`GET /state`**: state machine + gating inputs (see `backend/services/execution_service/app.py`).
- **Safety dependencies**
  - Kill-switch (`EXECUTION_HALTED`) + state machine policy (see `docs/EXECUTION_AGENT_STATE_MACHINE.md`).
  - Marketdata freshness (`docs/MARKETDATA_HEALTH_CONTRACT.md`).

### `mission-control` (ops aggregator; optional)

- **Must do**
  - Generate an operational snapshot: deploy report, marketdata heartbeat sample, and any warning events.
  - Write artifacts into `audit_artifacts/ops_runs/` with timestamps.
- **Must never do**
  - Change `AGENT_MODE`, scale workloads, patch resources, or toggle kill-switch.
- **Health contract endpoints**
  - N/A (batch utility).
- **Safety dependencies**
  - Read-only cluster access (RBAC).
  - `scripts/report_v2_deploy.sh` (read-only reporting).

### `reporting-agent` (deploy report)

- **Must do**
  - Produce deterministic `audit_artifacts/deploy_report.md` and `.json` (see `docs/ops/reporting.md`).
- **Must never do**
  - Modify cluster state.
- **Health contract endpoints**
  - N/A.
- **Safety dependencies**
  - `kubectl` configured and authorized for read access.

### `congressional-ingest` (if used)

- **Must do**
  - Periodically ingest disclosures and publish normalized events.
- **Must never do**
  - Execute trades.
- **Health contract endpoints**
  - Cloud Run service should expose `GET /health` (implementation-dependent).
- **Safety dependencies**
  - Quiver API secret (Secret Manager).
  - NATS availability.

---

## Ops cadence (expectations + owners)

All time anchors are **US market time**; translate to your deployment region as needed. These tasks are *read-only posture checks* unless explicitly marked otherwise.

### Pre-market (T-60 minutes)

- **Generate deploy posture report** (`reporting-agent`)
  - Run `./scripts/ops_pre_market.sh`
  - Artifact: `audit_artifacts/ops_runs/*_pre_market/` + `audit_artifacts/deploy_report.md`
- **Verify kill-switch is HALTED** (human-on-call)
  - Confirm `EXECUTION_HALTED=1` (k8s ConfigMap default is halted).
- **Verify marketdata heartbeat is healthy** (`mission-control` or human)
  - Sample `MARKETDATA_HEALTH_URL` and confirm `ok=true` and `age_seconds <= max_age_seconds`.

### Pre-market (T-15 minutes)

- **Re-check marketdata freshness** (`mission-control` or human)
- **Check cluster warnings** (`reporting-agent`)
  - Look for `ImagePullBackOff`, `CrashLoopBackOff`, pending pods, or resource pressure.

### Market open posture (T+0 to T+15)

- **Hold execution disabled** (human-on-call)
  - `execution-agent` remains OFF.
- **Observe strategy runtime stability** (human/mission-control)
  - No crash loops, no repeated stale-marketdata refusals.

### Intraday monitoring cadence

- **Every 15 minutes**: marketdata heartbeat + pod health sampling (`mission-control` optional; otherwise human checks)
- **On alerts**: follow runbooks (below) and preserve artifacts in `audit_artifacts/ops_runs/`.

### Post-market (T+30 minutes after close)

- **Generate post-market operational snapshot** (`reporting-agent`)
  - Run `./scripts/ops_post_market.sh`
  - Artifacts: deploy report + logs/events snapshot + marketdata heartbeat sample
- **Archive key artifacts** (human/CI)
  - Ensure `audit_artifacts/` is persisted by CI/CD or copied to durable storage.

---

## Failure modes matrix (symptom → cause → action → verification)

| Symptom | Likely cause | Immediate action (safe) | Verification |
|---|---|---|---|
| **Marketdata stale (`/healthz` returns 503)** | Upstream feed down, creds missing, streamer crash, clock skew | Follow runbook: `docs/ops/runbooks/marketdata_stale.md` | `curl $MARKETDATA_HEALTH_URL` returns 200; tick age within threshold |
| **Strategy runtime halted/refusing** | Marketdata stale, kill-switch active, missing env, downstream store unavailable | Follow runbook: `docs/ops/runbooks/strategy_engine_halted.md` | Strategies resume producing proposals; no crash loops |
| **CrashLoopBackOff** | Config error, missing secret, code exception | Follow runbook: `docs/ops/runbooks/crashloop_backoff.md` | Pod restarts stop; logs show normal steady-state |
| **ImagePullBackOff** | Registry auth, missing image/tag, quota | Follow runbook: `docs/ops/runbooks/image_pull_backoff.md` | Image pulls succeed; pods become Ready |
| **Cluster resource pressure (Pending pods / OOMKilled)** | Insufficient CPU/memory, noisy neighbors | Follow runbook: `docs/ops/runbooks/resource_pressure.md` | Pods scheduled + stable; no OOMKilled; metrics stable |

---

## Escalation rules (stop-the-line triggers)

- **P0 (page immediately / stop the line)**
  - Any indication that live execution might be enabled unintentionally.
  - Kill-switch misconfigured (cannot confirm `EXECUTION_HALTED` state) while `execution-agent` is not OFF.
  - Marketdata freshness gate is bypassed or returning false positives.
- **P1 (page during market hours)**
  - Marketdata stale for > 2 minutes during market hours.
  - Strategy runtime crash looping for > 5 minutes.
- **P2 (same day)**
  - Congressional ingest delayed or NATS unreachable, without impacting live posture.

**Human-only action: enabling execution**

Enabling `execution-agent` (scaling from 0 / setting LIVE) requires:

- Two-person review (operator + reviewer)
- Written change record (ticket/issue link)
- Evidence:
  - kill-switch state confirmed OFF **only for the execution window**
  - marketdata heartbeat healthy
  - deploy report “ok” for all critical components

This repository’s ops scripts do **not** implement that flow.

---

## References (existing docs)

- `docs/ops/reporting.md` — deployment report tool (read-only)
- `docs/KILL_SWITCH.md` — `EXECUTION_HALTED` contract and k8s ConfigMap guidance
- `docs/MARKETDATA_HEALTH_CONTRACT.md` — `/healthz` freshness gating contract
- `docs/EXECUTION_AGENT_STATE_MACHINE.md` — execution gating state machine

