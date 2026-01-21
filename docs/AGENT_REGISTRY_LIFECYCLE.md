# Centralized Agent Registry & Lifecycle Management (Spec)

This document defines a **centralized AgentRegistry** and a **lifecycle management system** for AgentTrader-style workloads.

It is designed to align with existing repo conventions:

- Firestore used as an **ops read model** (`updatedAt`, `lastHeartbeatAt`, server-written).
- Kill-switch is **defense-in-depth**: agents must enforce locally (env/file), while control-plane state is also visible in Firestore for ops/UI.

---

## AgentRegistry responsibilities

### 1) Agent metadata (identity + ownership)

The registry is the **source of truth** for:

- **Stable identity**: `agentId`, `displayName`, `kind` (service/strategy/execution), and `environment`.
- **Ownership**: `owner.team`, `owner.oncall`, `runbookUrl`, `repo`.
- **Deployment target**: `runtime.platform` (gke/cloudrun/functions), `runtime.region`, `runtime.namespace`, `runtime.workload`, `runtime.instanceId` (for per-instance observability).
- **Versioning**: `version.gitSha`, `version.imageTag`, `version.buildTime`.

### 2) Capabilities

Capabilities are used for **policy decisions**, routing, and safety constraints:

- **Execution**: `can_execute_live`, `can_execute_paper`
- **Decisioning**: `can_generate_signals`, `can_propose_orders`
- **Market data**: `can_ingest_marketdata`, `can_publish_heartbeats`
- **Ops**: `supports_remote_disable`, `supports_mode_switch`, `supports_config_reload`

Capabilities are stored as a **map of boolean flags** (keys are stable strings) to remain forward-compatible.

### 3) Modes (observe/shadow/paper)

The registry maintains:

- **Desired mode** (control-plane intent): `lifecycle.desiredState`
- **Observed mode** (what the agent reports): `lifecycle.observedState`
- **Effective mode** (after global safety overrides): `lifecycle.effectiveState`

Modes are expressed via lifecycle states:

- `OBSERVING`: observe-only (no paper/live execution)
- `SHADOW_ACTIVE`: shadow evaluation path active (no broker/paper execution)
- `PAPER_ACTIVE`: paper trading active (broker sandbox/paper endpoint only)

### 4) Health status

Health is represented separately from lifecycle state:

- **Health**: `health.status` (`healthy|degraded|down|unknown`)
- **Freshness**: `health.lastHeartbeatAt`, `health.heartbeatAgeSeconds`, `health.staleThresholdSeconds`
- **Diagnostics**: `health.reasonCodes[]`, `health.lastError`, `health.links{logs,metrics}`

Lifecycle state answers **“what should this agent be doing?”**  
Health answers **“is it currently able to do it safely?”**

---

## Lifecycle states (required)

These are the **registry lifecycle states** (control-plane states), distinct from internal per-process state machines.

- **`REGISTERED`**: known to the platform, allowed to run, but not yet enabled into a mode.
- **`OBSERVING`**: enabled in observe mode.
- **`SHADOW_ACTIVE`**: enabled in shadow evaluation mode.
- **`PAPER_ACTIVE`**: enabled in paper trading mode.
- **`DISABLED`**: explicitly disabled (should not run; or should refuse any trading/decisioning depending on capability).
- **`EMERGENCY_STOP`**: forced stop due to a safety event or operator action; highest-priority halt state.

### Storage encoding (Firestore)

Per repo convention, Firestore stores enums as **lower_snake_case strings**:

- `REGISTERED` → `registered`
- `OBSERVING` → `observing`
- `SHADOW_ACTIVE` → `shadow_active`
- `PAPER_ACTIVE` → `paper_active`
- `DISABLED` → `disabled`
- `EMERGENCY_STOP` → `emergency_stop`

### Runtime mapping (env vars)

To align with the existing runtime guardrails (`docs/CANONICAL_ENV_VAR_CONTRACT.md`):

- `OBSERVING` maps to `AGENT_MODE=OBSERVE`
- `SHADOW_ACTIVE` maps to `AGENT_MODE=EVAL`
- `PAPER_ACTIVE` maps to `AGENT_MODE=PAPER` (note: `TRADING_MODE=paper` is still required by the repo’s paper-lock)

---

## Firestore schema (proposed)

### Collection: `ops_agents/{agentId}`

Represents the **latest registry entry + lifecycle + health** for one agent.

**Document ID strategy**

- Stable, human-readable ID: `"{environment}.{agentName}"` (recommended)
  - Examples: `prod.strategy-engine`, `prod.execution-service`, `prod.marketdata-mcp-server`

**Top-level fields**

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `agentId` | string | ✅ | Must equal document ID (defensive denormalization). |
| `displayName` | string | ✅ | UI-friendly. |
| `kind` | string | ✅ | Enum: `service`, `strategy`, `execution`, `worker`, `cron`. |
| `environment` | string | ✅ | `dev|staging|prod` (or your convention). |
| `capabilities` | map | ✅ | `{"can_execute_paper": true, ...}` (booleans). |
| `lifecycle` | map | ✅ | Desired/observed/effective state, operator/audit fields. |
| `health` | map | ✅ | Latest health + heartbeat. |
| `owner` | map | ⛔ | Team ownership + contacts. |
| `runtime` | map | ⛔ | Platform/deployment coordinates. |
| `version` | map | ⛔ | Git/image metadata. |
| `labels` | map | ⛔ | Low-cardinality tags. |
| `meta` | map | ⛔ | Free-form; avoid high-cardinality indexed fields. |
| `createdAt` | timestamp | ✅ | Server timestamp. |
| `updatedAt` | timestamp | ✅ | Server timestamp for latest material change. |

**`lifecycle` map**

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `desiredState` | string | ✅ | One of `registered|observing|shadow_active|paper_active|disabled|emergency_stop`. Set by control plane. |
| `observedState` | string | ✅ | Same enum; reported by agent heartbeat (best-effort). |
| `effectiveState` | string | ✅ | Same enum; computed from desired state + safety overrides (kill-switch). |
| `stateReason` | string | ⛔ | Short explanation for effective state. |
| `lastTransitionAt` | timestamp | ✅ | When `effectiveState` last changed. |
| `lastDesiredChangeAt` | timestamp | ✅ | When `desiredState` last changed. |
| `changedBy` | map | ⛔ | `{actorType, actorId, actorEmail, ticket}`. |
| `lock` | map | ⛔ | Optional: prevents non-emergency transitions. |

**`health` map**

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `status` | string | ✅ | `healthy|degraded|down|unknown`. |
| `lastHeartbeatAt` | timestamp | ✅ | Updated by agent heartbeat materialization. |
| `heartbeatAgeSeconds` | number | ⛔ | Server-computed at write time (optional). |
| `staleThresholdSeconds` | number | ⛔ | From config; useful for UI. |
| `reasonCodes` | array | ⛔ | e.g. `["marketdata_stale","kill_switch_enabled"]`. |
| `lastError` | map | ⛔ | `{at, message, code}` (bounded). |
| `links` | map | ⛔ | `{logs, metrics, runbook}`. |

**Indexes**

Recommended (matches existing ops dashboard query patterns):

- Composite: `lifecycle.effectiveState`, `updatedAt`
- Composite: `health.status`, `health.lastHeartbeatAt`
- Single-field: `updatedAt`, `environment`, `kind`

### Subcollection (append-only audit): `ops_agents/{agentId}/events/{eventId}`

Used for transition/audit history (bounded/TTL-managed).

**Document ID strategy**

- `"{timestampMillis}_{shortHash}"` for ordering + dedupe friendliness.

**Fields**

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `at` | timestamp | ✅ | Event time (server). |
| `type` | string | ✅ | `desired_change`, `observed_heartbeat`, `effective_transition`, `emergency_stop`, `kill_switch_observed`. |
| `fromState` | string | ⛔ | For transitions. |
| `toState` | string | ⛔ | For transitions. |
| `actor` | map | ⛔ | `{actorType, actorId, actorEmail}`. |
| `reason` | string | ⛔ | Human-readable, bounded. |
| `meta` | map | ⛔ | Structured context; avoid secrets. |
| `expiresAt` | timestamp | ✅ | TTL field. |

---

## State transition rules (registry lifecycle)

### Transition authority

- **Control plane** (Mission Control / Ops API / Admin tooling) is the only actor that may write `lifecycle.desiredState`.
- Agents may write **observed** fields via heartbeat ingestion/materialization only (or publish events that materializers project into Firestore).

### Allowed transitions (desiredState)

The desired lifecycle state is governed by these rules:

1) `REGISTERED → OBSERVING | SHADOW_ACTIVE | PAPER_ACTIVE | DISABLED`
- Requires capability checks for target state.

2) `OBSERVING → SHADOW_ACTIVE | PAPER_ACTIVE | DISABLED`
- `PAPER_ACTIVE` requires `capabilities.can_execute_paper == true`.

3) `SHADOW_ACTIVE → OBSERVING | PAPER_ACTIVE | DISABLED`
- `PAPER_ACTIVE` requires `capabilities.can_execute_paper == true`.

4) `PAPER_ACTIVE → SHADOW_ACTIVE | OBSERVING | DISABLED`

5) `DISABLED → REGISTERED`
- Used to re-enable after maintenance; does not automatically enable any mode.

6) `* → EMERGENCY_STOP`
- Always allowed by an operator or automated safety controller.

7) `EMERGENCY_STOP → DISABLED` (default recovery path)
- Requires explicit operator action + reason/ticket.

8) `EMERGENCY_STOP → REGISTERED`
- Allowed only if the underlying emergency condition is cleared and an operator explicitly re-registers.

### Forbidden transitions (hard rules)

- Any direct transition **out of `EMERGENCY_STOP`** to an active mode (`OBSERVING|SHADOW_ACTIVE|PAPER_ACTIVE`) is forbidden.
  - Rationale: forces an explicit intermediate step (`DISABLED` or `REGISTERED`) with audit.

### Effective state computation (safety overlay)

`effectiveState` is computed as:

1) If **global kill switch is ON**, then:
- If `capabilities.can_execute_live == true` OR `capabilities.can_execute_paper == true` OR `capabilities.can_propose_orders == true`:
  - `effectiveState = EMERGENCY_STOP`
  - `stateReason = "global_kill_switch"`
- Else:
  - `effectiveState = desiredState` (non-trading agents can remain active)

2) Else if **agent-specific emergency stop is asserted** (operator or safety automation):
- `effectiveState = EMERGENCY_STOP`

3) Else:
- `effectiveState = desiredState`

Notes:

- Health does **not** automatically change lifecycle state. Instead, health drives alerts and SLOs; the control plane may choose to disable or emergency stop based on policy.

---

## Kill-switch integration (defense-in-depth)

This repo already implements an execution kill switch via:

- **Env var**: `EXECUTION_HALTED=1` (preferred) and legacy `EXEC_KILL_SWITCH=1`
- **File mount**: `EXECUTION_HALTED_FILE=/etc/agenttrader/kill-switch/EXECUTION_HALTED` (K8s ConfigMap volume)
- **K8s ConfigMap**: `agenttrader-kill-switch` with `EXECUTION_HALTED: "0"|"1"`
- **Optional Firestore** (documented): `ops/execution_kill_switch { enabled: true }`
- **Strategy-cycle safety** (separate): `agenttrader-safety` ConfigMap with `KILL_SWITCH: "true"|"false"`

### Integration contract

The centralized registry must:

- **Expose global kill state** to ops/UI (for situational awareness).
- **Never rely solely on Firestore** for the kill switch; agents must continue to hard-enforce locally via `backend/common/kill_switch.py`.

### Proposed Firestore representation (optional, ops visibility)

Create a top-level document:

- `ops_global_safety/execution_kill_switch`

Fields:

- `enabled` (boolean)
- `source` (string): `env`, `file`, `configmap`, `firestore`, `risk_manager`
- `effectiveAt` (timestamp)
- `reason` (string)
- `updatedAt` (timestamp)

The control plane can set this doc for visibility; execution agents still enforce via env/file checks.

### Precedence rules (recommended)

When determining “kill switch is ON” for effective state:

1) If `EXECUTION_HALTED` (env or file) is truthy ⇒ ON
2) Else if `ops_global_safety/execution_kill_switch.enabled == true` ⇒ ON
3) Else if risk management indicates trading disabled (e.g., `systemStatus/risk_management.trading_enabled == false`) ⇒ treat as ON for execution-capable agents
4) Else ⇒ OFF

---

## State machine diagram (textual)

Desired lifecycle state machine (with emergency overlay):

```
                         ┌───────────────────────┐
                         │       REGISTERED       │
                         └───────────┬───────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
          v                          v                          v
 ┌────────────────┐        ┌─────────────────┐        ┌─────────────────┐
 │   OBSERVING    │<──────>│  SHADOW_ACTIVE  │<──────>│  PAPER_ACTIVE   │
 └───────┬────────┘        └────────┬────────┘        └────────┬────────┘
         │                          │                          │
         └──────────────┬───────────┴───────────┬──────────────┘
                        v                       v
                 ┌──────────────┐      ┌──────────────────┐
                 │   DISABLED   │<────>│   REGISTERED      │
                 └──────┬───────┘      └──────────────────┘
                        │
                        │ (operator/safety: always allowed)
                        v
                 ┌──────────────────┐
                 │  EMERGENCY_STOP  │
                 └──────┬───────────┘
                        │
                        │ allowed exits:
                        │  - to DISABLED (default)
                        │  - to REGISTERED (explicit re-register)
                        v
                 ┌──────────────┐
                 │   DISABLED   │
                 └──────────────┘
```

Effective-state overlay:

- If global kill switch is ON and the agent has trading/proposal capability ⇒ `effectiveState = EMERGENCY_STOP` regardless of desired state.

---

## Example registry entries

### 1) `ops_agents/prod.marketdata-mcp-server`

```json
{
  "agentId": "prod.marketdata-mcp-server",
  "displayName": "Marketdata MCP Server",
  "kind": "service",
  "environment": "prod",
  "capabilities": {
    "can_ingest_marketdata": true,
    "can_publish_heartbeats": true,
    "can_generate_signals": false,
    "can_propose_orders": false,
    "can_execute_paper": false,
    "can_execute_live": false,
    "supports_remote_disable": true,
    "supports_mode_switch": false
  },
  "lifecycle": {
    "desiredState": "observing",
    "observedState": "observing",
    "effectiveState": "observing",
    "stateReason": "ok",
    "lastTransitionAt": "2026-01-21T00:00:00Z",
    "lastDesiredChangeAt": "2026-01-21T00:00:00Z",
    "changedBy": { "actorType": "ops", "actorId": "mission-control", "ticket": "INC-1234" }
  },
  "health": {
    "status": "healthy",
    "lastHeartbeatAt": "2026-01-21T00:00:00Z",
    "staleThresholdSeconds": 30
  },
  "owner": {
    "team": "marketdata",
    "oncall": "marketdata-oncall",
    "runbookUrl": "docs/runbooks/marketdata_stale.md"
  },
  "runtime": {
    "platform": "gke",
    "namespace": "trading-floor",
    "workload": "deployment/marketdata-mcp-server",
    "region": "us-central1"
  },
  "version": { "gitSha": "a2466ec", "imageTag": "marketdata-mcp-server:a2466ec" },
  "labels": { "subsystem": "marketdata" },
  "createdAt": "2026-01-21T00:00:00Z",
  "updatedAt": "2026-01-21T00:00:00Z"
}
```

### 2) `ops_agents/prod.strategy-engine`

```json
{
  "agentId": "prod.strategy-engine",
  "displayName": "Strategy Engine",
  "kind": "service",
  "environment": "prod",
  "capabilities": {
    "can_ingest_marketdata": false,
    "can_publish_heartbeats": true,
    "can_generate_signals": true,
    "can_propose_orders": true,
    "can_execute_paper": false,
    "can_execute_live": false,
    "supports_remote_disable": true,
    "supports_mode_switch": true
  },
  "lifecycle": {
    "desiredState": "shadow_active",
    "observedState": "shadow_active",
    "effectiveState": "shadow_active",
    "stateReason": "shadow_eval_enabled",
    "lastTransitionAt": "2026-01-21T00:00:00Z",
    "lastDesiredChangeAt": "2026-01-21T00:00:00Z",
    "changedBy": { "actorType": "ops", "actorId": "mission-control", "ticket": "CHG-9881" }
  },
  "health": {
    "status": "healthy",
    "lastHeartbeatAt": "2026-01-21T00:00:00Z",
    "staleThresholdSeconds": 30
  },
  "owner": { "team": "strategies", "oncall": "strategies-oncall" },
  "runtime": { "platform": "gke", "namespace": "trading-floor", "workload": "deployment/strategy-engine", "region": "us-central1" },
  "labels": { "subsystem": "strategy" },
  "createdAt": "2026-01-21T00:00:00Z",
  "updatedAt": "2026-01-21T00:00:00Z"
}
```

### 3) `ops_agents/prod.execution-service` (kill-switch forces effective emergency stop)

```json
{
  "agentId": "prod.execution-service",
  "displayName": "Execution Service",
  "kind": "execution",
  "environment": "prod",
  "capabilities": {
    "can_publish_heartbeats": true,
    "can_propose_orders": true,
    "can_execute_paper": true,
    "can_execute_live": true,
    "supports_remote_disable": true,
    "supports_mode_switch": true
  },
  "lifecycle": {
    "desiredState": "paper_active",
    "observedState": "paper_active",
    "effectiveState": "emergency_stop",
    "stateReason": "global_kill_switch",
    "lastTransitionAt": "2026-01-21T00:00:00Z",
    "lastDesiredChangeAt": "2026-01-21T00:00:00Z",
    "changedBy": { "actorType": "ops", "actorId": "mission-control", "ticket": "INC-7777" }
  },
  "health": {
    "status": "healthy",
    "lastHeartbeatAt": "2026-01-21T00:00:00Z",
    "reasonCodes": ["kill_switch_enabled"],
    "staleThresholdSeconds": 30
  },
  "owner": { "team": "execution", "oncall": "execution-oncall" },
  "runtime": { "platform": "cloudrun", "region": "us-central1", "workload": "execution-service" },
  "createdAt": "2026-01-21T00:00:00Z",
  "updatedAt": "2026-01-21T00:00:00Z"
}
```

