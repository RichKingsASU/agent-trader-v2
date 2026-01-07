# AgentTrader v2 — Day 1 Ops Playbook (Post-Lock Default Mode)

**Production is locked. This document defines operations only.**

## Non‑Negotiables (Post‑Lock Guardrails)

- **Trading execution must remain disabled.** Do not enable `AGENT_MODE=EXECUTE`, do not introduce any path that places broker orders.
- **Global kill switch remains ON by default** (`EXECUTION_HALTED=1`) and is treated as a safety invariant, not a “feature toggle”.
- **No drift / no ambiguity**: all “Day 1” operations are either always‑on, scheduled, or explicitly on‑demand.
- **Read‑only posture**: Day 1 automation may only *observe*, *report*, and *capture artifacts*.

## Definitions

- **Expected state**
  - **OK**: service is healthy and serving its contract.
  - **MARKET_CLOSED**: service is healthy; market-dependent signals may be stale by design.
  - **HALTED**: service continues to run, but any execution-capable paths are refused due to kill switch / policy.
- **NYSE hours baseline** (America/New_York): market open \(09:30\), close \(16:00\), Mon–Fri, excluding holidays.
  - All cron schedules below assume **America/New_York** and must account for DST.

---

## A) Always‑On Services

These services run continuously. Their behavior changes with market hours and kill switch state, but the processes stay up.

### `marketdata-mcp-server`

- **Purpose**: Provide market data heartbeat + MCP interface; produce fresh ticks when market is open.
- **Expected state**
  - **OK**: during market hours with fresh ticks.
  - **MARKET_CLOSED**: outside market hours (stale tick is expected).
  - **HALTED**: kill switch may be ON; this service still runs but logs kill-switch state (no execution behavior).
- **Health contract**
  - **`GET /healthz`** returns heartbeat JSON; returns **200** when fresh, **503** when stale. See `docs/MARKETDATA_HEALTH_CONTRACT.md`.
  - (Optional) **`GET /heartbeat`** may be sampled by the deployment report.
- **Restart policy**: Kubernetes `Deployment` with `replicas: 1`; restart-on-crash; no manual restarts unless repeatedly crashlooping.
- **Alert ownership**: Ops on-call (primary), Platform/Backend (secondary).

### `strategy-engine`

> Implementation note: in this repo, strategy runtimes are deployed as StatefulSets (e.g. `gamma-strategy`, `whale-strategy`) using the `strategy-runtime` image.

- **Purpose**: Generate *non-executing* strategy outputs; refuse to run when marketdata is stale; never place orders.
- **Expected state**
  - **HALTED**: default posture post-lock (kill switch ON).
  - **MARKET_CLOSED**: allowed to idle with no work while market is closed.
  - **OK**: only means “healthy + producing non-executing artifacts”; **does not** mean execution is allowed.
- **Health contract**
  - **Must enforce marketdata freshness gate**: if marketdata is stale/unreachable, strategy refuses to proceed. See `docs/MARKETDATA_HEALTH_CONTRACT.md`.
  - **`GET /healthz`** (where exposed) must include build fingerprint fields and a “mode” indicator (non-executing).
- **Restart policy**: Kubernetes `StatefulSet` `replicas: 1` per strategy; restart-on-crash; treat CrashLoopBackOff as a paging condition during market hours.
- **Alert ownership**: Ops on-call (primary), Strategy/Backend (secondary).

### `mission-control`

- **Purpose**: Human-facing control plane for visibility (system state + logs). In Day 1 Ops, it is **observability-first**.
- **Expected state**
  - **OK**: UI reachable; Firestore subscriptions functional.
  - **MARKET_CLOSED**: same as OK (UI remains up).
  - **HALTED**: if kill switch is active, Mission Control must *display* it prominently; it must not offer any execution enablement.
- **Health contract**
  - UI loads without errors.
  - Firestore: system heartbeat updates within 30s during active periods (if configured).
- **Restart policy**: managed hosting / deployment platform default (restart on crash; immutable release).
- **Alert ownership**: Ops on-call (primary), Frontend (secondary).

### `ops-ui`

- **Purpose**: Operations dashboards (job health, news, ops overview) for calm monitoring.
- **Expected state**
  - **OK**: UI reachable and renders.
  - **MARKET_CLOSED**: same as OK.
  - **HALTED**: should still render, and should not present any execution toggles.
- **Health contract**: UI route health (HTTP 200), key pages render without runtime errors.
- **Restart policy**: managed hosting / deployment platform default.
- **Alert ownership**: Ops on-call (primary), Frontend (secondary).

---

## B) Scheduled Operations (Automated)

All schedules are **cron-style** in **America/New_York** time.

> Implementation guidance: run these via a scheduler that supports `TZ=America/New_York` (e.g., Cloud Scheduler → Cloud Run Job wrapper). These jobs must remain **read-only** and must never mutate production state.

### 1) Pre‑market readiness check (T–60)

- **Schedule (NY)**: `30 8 * * 1-5`
- **Command**: `./scripts/readiness_check.sh --namespace trading-floor`
- **Expected artifacts**
  - `audit_artifacts/readiness_check/<timestamp>/readiness_report.md`
- **Failure behavior**
  - **FAIL** triggers an Ops alert and blocks any discretionary changes that day.
  - No automated remediation.

### 2) Pre‑market readiness check (T–15)

- **Schedule (NY)**: `15 9 * * 1-5`
- **Command**: `./scripts/readiness_check.sh --namespace trading-floor`
- **Expected artifacts**
  - `audit_artifacts/readiness_check/<timestamp>/readiness_report.md`
- **Failure behavior**
  - **FAIL** triggers an Ops alert and initiates the “market open posture verification” early as a diagnostic step.

### 3) Market open posture verification (T+5)

- **Schedule (NY)**: `35 9 * * 1-5`
- **Command**: `./scripts/report_v2_deploy.sh --skip-health`
- **Expected artifacts**
  - `audit_artifacts/deploy_report.md`
  - `audit_artifacts/deploy_report.json`
- **Failure behavior**
  - If the report cannot be generated: alert Ops.
  - If the report indicates execution is allowed (e.g., kill switch off): **page immediately** (see Alert Rules).

### 4) Post‑market report capture (T+30)

- **Schedule (NY)**: `30 16 * * 1-5`
- **Command**: `./scripts/report_v2_deploy.sh --skip-health`
- **Expected artifacts**
  - `audit_artifacts/deploy_report.md`
  - `audit_artifacts/deploy_report.json`
- **Failure behavior**
  - Informational alert; retry once after 10 minutes; if still failing, record as a missed artifact and investigate next business day.

### 5) Daily LKG capture (after market close)

- **Schedule (NY)**: `0 17 * * 1-5`
- **Command**: `./scripts/capture_config_snapshot.sh --lkg`
- **Expected artifacts**
  - `audit_artifacts/lkg/<YYYY-MM-DD>/config_snapshot.md`
  - `audit_artifacts/lkg/<YYYY-MM-DD>/config_snapshot.sha256`
- **Failure behavior**
  - Informational alert (non-paging) unless it fails 2 business days in a row.

---

## C) On‑Demand Operations

These are run only when needed. They are **read-only** and produce auditable artifacts.

- **`readiness_check.sh`** (`./scripts/readiness_check.sh`)
  - **When/why**: before market open, after any infra incident, or when “unknown state” is reported.
  - **Output**: readiness report artifact under `audit_artifacts/readiness_check/`.

- **Deploy report** (`./scripts/report_v2_deploy.sh` or `make report`)
  - **When/why**: any time you need a one-page “what is deployed + is it allowed” snapshot.
  - **Output**: `audit_artifacts/deploy_report.{md,json}` (see `docs/ops/reporting.md`).

- **`capture_config_snapshot`** (`./scripts/capture_config_snapshot.sh`)
  - **When/why**: after any investigation, after alerts, or to establish “known-good” baselines.
  - **Output**: checksums + manifest of operationally relevant files.

- **Postmortem replay** (`./scripts/postmortem_replay.sh`)
  - **When/why**: after an incident to reconstruct timeline from logs (stdin or files).
  - **Output**: `audit_artifacts/postmortem_replay/<timestamp>/replay_timeline.md`.

- **Blueprint generator** (`./scripts/generate_blueprint.sh`)
  - **When/why**: produce a deterministic “what exists” snapshot for audits / onboarding.
  - **Output**: `audit_artifacts/blueprint/<timestamp>/blueprint.md`.

---

## D) Artifact Lifecycle

### Where artifacts are written

- **Primary**: `audit_artifacts/`
- **Recommended subtrees**
  - `audit_artifacts/readiness_check/<timestamp>/...`
  - `audit_artifacts/postmortem_replay/<timestamp>/...`
  - `audit_artifacts/blueprint/<timestamp>/...`
  - `audit_artifacts/lkg/<YYYY-MM-DD>/...` (daily immutable baseline)

### Retention expectations (institutional calm)

- **Readiness checks**: 30 days
- **Deploy reports**: 90 days
- **Blueprint snapshots**: 180 days (or regenerate on demand)
- **Postmortem replays**: 1 year minimum (audit trail)
- **LKG**: retain indefinitely (or per policy); these are baselines

### When artifacts are reviewed

- **Daily**: the T+5 (open posture) deploy report is reviewed by Ops.
- **Weekly**: review readiness failure trends and top issues from deploy reports.
- **After incidents**: replay timeline + config snapshot are reviewed in postmortem.

### Immutable after creation

- **Immutable**: `audit_artifacts/lkg/**`, any postmortem replay artifacts, any deploy report used as evidence for an incident.
- **Mutable**: none; if you need a correction, generate a new artifact with a new timestamp.

---

## E) Alert Handling Rules

### Paging (immediate human response required)

- **Kill switch is OFF / execution appears allowed**
  - Signal: deploy report shows workloads “LIVE”, or `EXECUTION_HALTED` is not truthy in cluster.
  - Runbook: `docs/KILL_SWITCH.md`

- **Marketdata stale during market open**
  - Signal: `/healthz` stale (503) during market hours, or strategies refuse due to `marketdata_stale`.
  - Runbook: `docs/MARKETDATA_HEALTH_CONTRACT.md`

- **CrashLoopBackOff for `marketdata-mcp-server` or strategy runtimes during market hours**
  - Signal: deploy report “Top Issues” includes crashloop.
  - Runbook: `docs/ops/reporting.md`

### Informational (non-paging)

- Post-market report capture failed once (auto retry acceptable).
- LKG capture missed once.
- Marketdata is stale outside market hours (expected).

### Ignored during MARKET_CLOSED

- Heartbeat staleness warnings (as long as services are reachable).
- Strategy idling / no tick activity.

### Alert → runbook mapping (canonical)

- **Execution safety / kill switch** → `docs/KILL_SWITCH.md`
- **Marketdata heartbeat** → `docs/MARKETDATA_HEALTH_CONTRACT.md`
- **Deployment posture** → `docs/ops/reporting.md`
- **Replay timelines** → `docs/REPLAY_LOG_SCHEMA.md`

---

## F) Human‑Only Actions (Explicit)

These actions must **never** be automated (agents must refuse):

- Enabling **EXECUTE** paths (e.g., setting `AGENT_MODE=EXECUTE`, broker order placement enablement).
- Flipping the global kill-switch (on/off) in production.
- Approving or changing strategy configs in production.
- Deploying to production (any `kubectl apply`, Cloud Run deploy, scheduler creation).
- Unlocking production lock or modifying locked artifacts.

---

## G) Agent Autonomy Contract

### What agents may do without approval (read-only only)

- Run `readiness_check.sh`, `report_v2_deploy.sh`, `capture_config_snapshot.sh`, `postmortem_replay.sh`, `generate_blueprint.sh`.
- Write artifacts under `audit_artifacts/**`.
- Open/append incident notes **as artifacts** (never by modifying production config).
- Escalate alerts to humans with a short, evidence-backed summary.

### What agents must refuse to do

- Any action that could enable execution (directly or indirectly).
- Any change to prod cluster state (no deploys, no configmap patches, no scheduler/job creation).
- Any change to locked artifacts or security posture.

### How agents prove compliance

- Every autonomous run must produce a timestamped artifact containing:
  - the command invoked,
  - git SHA,
  - environment identifiers available (kubectl context if present),
  - PASS/FAIL outcome and reasons.
- Agents must prefer existing read-only scripts and must not “improvise” mutations.

---

## “Forever Loop” (ASCII)

```text
                (America/New_York, Mon–Fri)

      ┌───────────────────────────────────────────────┐
      │                 MARKET CLOSED                  │
      │  - marketdata may be stale (expected)          │
      │  - strategies idle / refuse stale execution    │
      └───────────────┬───────────────────────────────┘
                      │
                      │  08:30  T–60  readiness_check  ───► audit_artifacts/readiness_check/...
                      │  09:15  T–15  readiness_check  ───► audit_artifacts/readiness_check/...
                      ▼
      ┌───────────────────────────────────────────────┐
      │                 MARKET OPEN                    │
      │  09:35  T+5   posture verification             │
      │        (deploy report; execution must be OFF)  │
      │        ──────────────────────────────────────► │
      │        audit_artifacts/deploy_report.{md,json} │
      │                                               │
      │  Alerts boundary:                               │
      │   - kill switch OFF  ==> PAGE HUMAN             │
      │   - marketdata stale ==> PAGE HUMAN             │
      └───────────────┬───────────────────────────────┘
                      │
                      │  16:30  T+30  post-market report ─► audit_artifacts/deploy_report.{md,json}
                      │  17:00        daily LKG capture   ─► audit_artifacts/lkg/YYYY-MM-DD/...
                      ▼
      ┌───────────────────────────────────────────────┐
      │                 MARKET CLOSED                  │
      └───────────────────────────────────────────────┘
```

