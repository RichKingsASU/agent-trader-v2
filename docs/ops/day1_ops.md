# AgentTrader v2 — Day 1 Ops Playbook (Post-Lock Default Mode)

**Status**: production-locked (observe-only).  
**Absolute rule**: **do not enable trading execution**. No automation may change `AGENT_MODE` to `EXECUTE`/`LIVE`, flip the kill-switch, deploy, or scale execution workloads.

This playbook defines the calm, institutional “what runs forever” operating model:
- what runs continuously
- what runs on schedule
- what runs only on demand
- what agents may do autonomously vs what humans must do

Scope anchors:
- Production lock: `ops/PRODUCTION_LOCK.md`
- Ops status semantics: `docs/ops/status_contract.md`
- Pre/post runbooks: `docs/ops/runbooks/pre_market.md`, `docs/ops/runbooks/post_market.md`

---

## A) Always-On Services

All services must expose a **health contract** that supports deterministic operations:
- **Primary**: `GET /ops/status` (preferred; stable state machine)
- **Secondary**: `GET /healthz` (marketdata freshness gating)
- **Tertiary**: `GET /health` (basic liveness)

States referenced below are from the shared contract: `OK | MARKET_CLOSED | HALTED` (see `docs/ops/status_contract.md`).

### 1) `marketdata-mcp-server`

- **Purpose**: ingest/normalize market data and provide freshness-gated access for downstream services.
- **Expected state**:
  - **Market hours**: `OK`
  - **Market closed**: `MARKET_CLOSED` (not an alert if otherwise healthy)
  - **If stale/unreachable**: downstream must treat as hard-stop (strategy must refuse to run).
- **Health contract**:
  - `GET /healthz` returns `200` with `{"ok": true, ...}` when fresh; `503` when stale.
  - `GET /ops/status` exposes `status.state` and `marketdata.is_fresh`.
- **Restart policy**:
  - Kubernetes `restartPolicy: Always` via Deployment + liveness/readiness probes.
  - Any restart loop is an incident (see runbook mapping below).
- **Alert ownership**: **Ops On-Call** (primary), **Marketdata Owner** (secondary).

### 2) `strategy-engine` (strategy runtime workloads)

- **Purpose**: generate **observe-only** proposals/decisions, strictly gated by marketdata freshness and kill-switch safety posture.
- **Expected state**:
  - **Market hours + fresh marketdata**: `OK` (observe-only; proposals allowed)
  - **Market closed**: `MARKET_CLOSED`
  - **Kill-switch active**: may report `HALTED` (expected default posture) but must never execute.
- **Health contract**:
  - `GET /ops/status` must report:
    - `safety.safe_to_execute_orders=false` **always** under production lock
    - `safety.safe_to_run_strategies=true/false` depending on marketdata freshness and posture
  - If marketdata is stale: strategy should refuse to run and report `HALTED` with `MARKETDATA_STALE` reason codes.
- **Restart policy**:
  - Kubernetes StatefulSets with probes; persistent crash loops are handled as incidents.
- **Alert ownership**: **Ops On-Call** (primary), **Strategy Owner** (secondary).

### 3) `mission-control`

- **Purpose**: read-only operational control plane API that aggregates `/ops/status` across services and exposes a stable UI-facing API.
- **Expected state**:
  - `OK` during market hours and off-hours (it is not market-hour dependent)
  - If upstream services are unreachable: mission-control can remain `OK` but will mark those dependencies `OFFLINE`.
- **Health contract**:
  - Exposes read-only API endpoints (see `docs/ops/mission_control.md`).
  - Does **not** implement any write endpoints by design.
- **Restart policy**:
  - Kubernetes Deployment with probes; crash loops are incidents.
- **Alert ownership**: **Ops On-Call** (primary), **Platform Owner** (secondary).

### 4) `ops-ui`

- **Purpose**: read-only dashboard for mission-control status, recent events, and latest deploy report.
- **Expected state**:
  - `OK` whenever reachable; can be `OFFLINE` without impacting safety (non-critical).
- **Health contract**:
  - Static UI serving + ability to reach mission-control base URL.
  - UI must not expose controls that mutate production state (post-lock default).
- **Restart policy**:
  - Kubernetes Deployment; non-critical restarts.
- **Alert ownership**: **Ops On-Call** (informational) / **UI Owner** (secondary).

---

## B) Scheduled Operations (Automated)

**Timezone**: schedules are specified in **America/New_York** local time unless stated otherwise. Your scheduler must run with `TZ=America/New_York` (or convert to UTC explicitly).

**Safety baseline** (all scheduled jobs):
- read-only
- fail-closed
- must not change kill-switch or `AGENT_MODE`
- must not deploy/scale/patch production workloads

### Schedule table (NYSE equities reference)

Market open: **09:30 ET** (T=0)  
Market close: **16:00 ET**

1) **Pre-market readiness check (T–60)** — 08:30 ET, Mon–Fri
- **Cron**: `30 8 * * 1-5`
- **Command**:
  - `./scripts/readiness_check.sh --namespace trading-floor`
  - Optional evidence bundle: `./scripts/ops_pre_market.sh`
- **Expected artifacts**:
  - `audit_artifacts/readiness_report.md`
  - `audit_artifacts/readiness_report.json`
  - Optional: `audit_artifacts/ops_runs/<UTC>_pre_market/*`
- **Failure behavior**:
  - **NO-GO** for the day until remediated (no automation escalates privileges or changes posture).
  - Alert **Ops On-Call**; follow runbooks in section E.

2) **Pre-market readiness check (T–15)** — 09:15 ET, Mon–Fri
- **Cron**: `15 9 * * 1-5`
- **Command**:
  - `./scripts/readiness_check.sh --namespace trading-floor`
- **Expected artifacts**:
  - overwrite-safe by design: readiness report is regenerated (retain via ops snapshot run dirs if required).
- **Failure behavior**:
  - **NO-GO**; page **Ops On-Call** if market opens in < 15 minutes.

3) **Market open posture verification (T+5)** — 09:35 ET, Mon–Fri
- **Cron**: `35 9 * * 1-5`
- **Command**:
  - `./scripts/report_v2_deploy.sh --namespace trading-floor`
  - `./scripts/readiness_check.sh --namespace trading-floor`
- **Expected artifacts**:
  - `audit_artifacts/deploy_report.md`
  - `audit_artifacts/deploy_report.json`
  - `audit_artifacts/readiness_report.{md,json}`
- **Failure behavior**:
  - If marketdata is stale or strategies are unhealthy: keep posture conservative (default) and treat as incident.

4) **Post-market report capture (T+30)** — 16:30 ET, Mon–Fri
- **Cron**: `30 16 * * 1-5`
- **Command**:
  - `./scripts/ops_post_market.sh`
  - `./scripts/report_v2_deploy.sh --namespace trading-floor`
  - Optional: `./scripts/readiness_check.sh --namespace trading-floor || true`
- **Expected artifacts**:
  - `audit_artifacts/ops_runs/<UTC>_post_market/*`
  - `audit_artifacts/deploy_report.{md,json}`
  - Optional: `audit_artifacts/readiness_report.{md,json}`
- **Failure behavior**:
  - Capture artifacts best-effort; alert **Ops On-Call** if critical workloads are failing.

5) **Daily LKG capture (after market close)** — 17:00 ET, Mon–Fri
- **Cron**: `0 17 * * 1-5`
- **Command**:
  - `./scripts/capture_lkg.sh trading-floor`
- **Expected artifacts**:
  - `ops/lkg/lkg_manifest.yaml` (kubectl-applyable, pinned to digests)
  - `ops/lkg/lkg_metadata.json` (provenance + safety posture)
- **Failure behavior**:
  - Alert **Ops On-Call** (informational unless required for an incident/rollback).
  - **Never** auto-tag or push git tags from automation; tagging is human-only change control.

---

## C) On-Demand Operations

These are run manually by humans or autonomously by agents **only when asked** (or when a scheduled job fails and capture is needed). All must be read-only.

### `readiness_check.sh`
- **Command**: `./scripts/readiness_check.sh --namespace trading-floor`
- **When/why**:
  - before market open, after incidents, after deploys (human-only deploy), or when alerts fire
  - to generate deterministic GO/NO-GO evidence

### `deploy_report` (deployment snapshot report)
- **Command**: `./scripts/report_v2_deploy.sh --namespace trading-floor`
- **When/why**:
  - to answer “what is currently deployed and healthy?” with a single artifact
  - to attach evidence to incidents and post-market summaries

### `capture_config_snapshot`
- **Command**: `./scripts/capture_config_snapshot.sh --namespace trading-floor`
- **When/why**:
  - before/after significant operational events (incidents, controlled unlock review, DR rehearsal)
  - to capture configuration *without* secrets (names and metadata only)

### `postmortem replay`
- **Command**:
  - `python3 ./scripts/replay_from_logs.py -o audit_artifacts/replays/<UTC>_replay.md <logfile(s)>`
- **When/why**:
  - after incidents to reconstruct a timeline of decisions and safety gating
  - to prove “no execution occurred” by inspecting intents and decision checkpoints

### `blueprint generator`
- **Command**: `./scripts/blueprint_generator.sh --namespace trading-floor`
- **When/why**:
  - when onboarding operators, during audits, and for incident context
  - produces a “what runs forever” inventory snapshot (services, manifests, endpoints)

---

## D) Artifact Lifecycle

### Where artifacts are written

- **Readiness**:
  - `audit_artifacts/readiness_report.md`
  - `audit_artifacts/readiness_report.json`
- **Deploy report**:
  - `audit_artifacts/deploy_report.md`
  - `audit_artifacts/deploy_report.json`
- **Ops run snapshots** (pre/post):
  - `audit_artifacts/ops_runs/<UTC>_{pre_market|post_market}/`
- **LKG (Last Known Good)**:
  - `ops/lkg/lkg_manifest.yaml`
  - `ops/lkg/lkg_metadata.json`
- **Config snapshots** (read-only):
  - `audit_artifacts/config_snapshots/<UTC>/`
- **Blueprint snapshots**:
  - `audit_artifacts/blueprints/<UTC>/blueprint.md`
- **Replay timelines**:
  - `audit_artifacts/replays/<UTC>_replay.md`

### Retention expectations (institutional default)

- **Minimum local retention**: 30 trading days for `audit_artifacts/ops_runs/` and incident artifacts.
- **Durable retention**: copy `audit_artifacts/` to your approved durable store (object storage / SIEM) daily.
- **LKG retention**: keep at least the last **30** LKG snapshots.

### When artifacts are reviewed

- **Daily**:
  - review T–15 readiness report + T+30 post-market snapshot summary
- **Weekly**:
  - spot-check LKG metadata + marketdata freshness trends
- **Incident-driven**:
  - always attach: deploy report + readiness report + ops snapshot directory + replay timeline (if logs available)

### Immutability rules

Artifacts are **immutable after creation**:
- any `audit_artifacts/ops_runs/<UTC>_*/` directory contents
- any `audit_artifacts/*_replay.md` replay output
- any `ops/lkg/*` snapshot (treat as a release record)

If corrections are required, create a **new** artifact with a new timestamp and cross-reference the previous one.

---

## E) Alert Handling Rules

### Immediate human response (page)

- **Marketdata stale during market hours**
  - Symptom: `marketdata /healthz` non-200 or `/ops/status` reason `MARKETDATA_STALE`
  - Runbook: `docs/ops/runbooks/marketdata_stale.md`
- **CrashLoopBackOff / ImagePullBackOff on critical workloads**
  - Runbook: `docs/ops/runbooks/crashloop_backoff.md`, `docs/ops/runbooks/image_pull_backoff.md`
- **Strategy runtime halting unexpectedly (not market closed)**
  - Runbook: `docs/ops/runbooks/strategy_engine_halted.md`
- **Any evidence of execution enablement**
  - Examples: `AGENT_MODE=EXECUTE|LIVE`, execution workloads scaled > 0, kill-switch not halted
  - Runbook: treat as Sev-0; follow production lock escalation in `ops/PRODUCTION_LOCK.md`

### Informational (ticket/async)

- `MARKET_CLOSED` states after hours (expected)
- Ops UI offline while mission-control remains healthy
- LKG capture failure when no incident is active

### Ignored during market closed (unless persistent next day)

- Marketdata stale after hours
- Strategy `MARKET_CLOSED` posture

---

## F) Human-Only Actions (Explicit)

These actions must **never** be automated (by scripts, cron, agents, or CI):

- enabling **EXECUTE** / LIVE trading (any form)
- flipping the kill-switch away from `EXECUTION_HALTED="1"`
- approving or changing strategy configs for production
- deploying to production (k8s apply, Cloud Run deploy, image rollouts)
- unlocking or modifying the production lock (`ops/PRODUCTION_LOCK.md` scope)
- creating/pushing release tags as part of automation (change control)

---

## G) Agent Autonomy Contract

### What agents may do without approval (read-only, evidence-first)

- run `./scripts/readiness_check.sh` and publish the reports as artifacts
- run `./scripts/report_v2_deploy.sh` and publish the deploy report artifacts
- run `./scripts/ops_pre_market.sh` / `./scripts/ops_post_market.sh` for snapshot capture
- generate replay timelines from logs using `scripts/replay_from_logs.py`
- generate blueprint/config snapshots (read-only) for audits and incident context
- open PRs that **only** add/adjust documentation, validators, and read-only tooling

### What agents must refuse to do (hard refusal)

- any change that could enable execution (directly or indirectly), including:
  - setting `AGENT_MODE=EXECUTE|LIVE`
  - scaling or deploying execution workloads
  - changing kill-switch defaults or live values
  - applying manifests to prod
- any modification to locked production artifacts in-place (requires controlled unlock process)

### How agents prove compliance

- **Artifacts**: every autonomous run produces timestamped evidence under `audit_artifacts/`
- **Logs**: command lines used and exit codes are captured in the artifact metadata files where applicable
- **Fail-closed**: on uncertainty (missing tools/cluster access), agents record `UNKNOWN/FAIL` and stop

---

## Forever Loop Diagram (ASCII)

```text
America/New_York trading day (Mon–Fri)

            ┌───────────────────────────────────────────────────────┐
            │                 ALWAYS-ON (steady state)              │
            │  marketdata-mcp-server  strategy-engine  mission-control │
            │                        ops-ui                           │
            └───────────────────────────────────────────────────────┘

   08:30  (T-60)  ─ readiness_check  ───────────────┐
      │                + ops_pre_market (optional)  │
      │                artifacts: readiness_report, ops_runs/*_pre_market
      ▼                                               │
   09:15  (T-15)  ─ readiness_check  ── ALERT BOUNDARY ├─ if FAIL ⇒ human response (NO-GO)
      ▼                                               │
   09:30  (OPEN)  ─ market opens ─────────────────────┘
      ▼
   09:35  (T+5)   ─ report_v2_deploy + readiness_check
      │                artifacts: deploy_report + readiness_report
      ▼
   16:00  (CLOSE) ─ market closes
      ▼
   16:30  (T+30)  ─ ops_post_market + report_v2_deploy (best-effort)
      │                artifacts: ops_runs/*_post_market + deploy_report
      ▼
   17:00          ─ capture_lkg (no tagging; evidence only)
                       artifacts: ops/lkg/lkg_manifest.yaml + lkg_metadata.json

Notes:
 - Execution stays disabled the entire time (kill-switch HALTED, no EXECUTE mode).
 - Any critical health failure during market hours triggers immediate human response.
```

