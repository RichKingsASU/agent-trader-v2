# Firestore Operational Dashboard — Schema

This schema is intended for **server-written read models** (Pub/Sub → Cloud Run consumer → Firestore) powering **realtime listeners** in an operational dashboard.

## Global constraints

- **No client-side writes**: documents are **mutated only by trusted server workloads** (Cloud Run / Admin SDK).
- **Realtime-friendly**: every primary document includes `updatedAt` (server timestamp) so clients can listen and render incremental updates efficiently.
- **Idempotent ingestion**: document ID strategies are chosen to support upserts/deduplication from event streams.

## Common field conventions

- **Timestamps**: Firestore `timestamp` values (not strings).
- **Server timestamps**: `createdAt`, `updatedAt`, and heartbeat fields should be written by server using Firestore server timestamp.
- **Enums**: store as **lower_snake_case strings** for forward compatibility.
- **Numbers**: store as Firestore `number`.
- **Maps**: store structured data under `meta`/`labels`/`stats` maps to avoid frequent schema churn.

---

## 1) `ops_services/{serviceId}`

Represents a runtime service (Cloud Run service, GKE workload, etc.) with current health and last-known heartbeat.

### Document ID strategy

- **Recommended**: stable, human-readable ID derived from platform identifiers.
  - Examples: `cloudrun.execution-engine`, `gke.strategy-engine`, `gke.marketdata-mcp-server`
- Enables **upsert by service** on every heartbeat/update event.

### Fields

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `serviceId` | string | ✅ | Must equal document ID (defensive denormalization). |
| `displayName` | string | ✅ | UI-friendly name. |
| `status` | string | ✅ | Enum: `healthy`, `degraded`, `down`, `unknown`, `maintenance`. |
| `updatedAt` | timestamp | ✅ | Server write time for latest material change. |
| `lastHeartbeatAt` | timestamp | ✅ | Last observed heartbeat/health signal. |
| `region` | string | ⛔ | e.g. `us-central1`. |
| `environment` | string | ⛔ | e.g. `dev`, `staging`, `prod`. |
| `version` | string | ⛔ | Git SHA / image tag. |
| `instanceCount` | number | ⛔ | Desired/active count depending on runtime. |
| `errorRate1m` | number | ⛔ | 0..1 or percent, be consistent. |
| `latencyP95Ms1m` | number | ⛔ | P95 latency over a short window. |
| `uptimeSeconds` | number | ⛔ | If tracked. |
| `links` | map | ⛔ | Deep links (logs, metrics, runbook). |
| `labels` | map | ⛔ | Low-cardinality tags (team, subsystem). |
| `meta` | map | ⛔ | Free-form server metadata (avoid high-cardinality in indexes). |

### Indexed fields

- **Composite (required for dashboard query)**: `status`, `updatedAt`
- **Single-field (default)**: `updatedAt`, `lastHeartbeatAt`, `environment`, `region`

### Suggested realtime query patterns

- List services by health: `where status == "degraded"` + `orderBy updatedAt desc`
- “Recently changed”: `orderBy updatedAt desc`

---

## 2) `ops_strategies/{strategyId}`

Represents a strategy runtime state (e.g., statefulset deployment, run mode, health, positions summary) as a read model.

### Document ID strategy

- **Recommended**: stable ID matching your strategy config key.
  - Examples: `gamma`, `whale`, `naive_flow_trend`

### Fields

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `strategyId` | string | ✅ | Must equal document ID. |
| `displayName` | string | ✅ | UI-friendly. |
| `status` | string | ✅ | Enum: `running`, `paused`, `error`, `stopped`, `unknown`. |
| `mode` | string | ✅ | Enum: `live`, `paper`, `shadow`, `backtest` (if applicable). |
| `updatedAt` | timestamp | ✅ | Server write time for latest material change. |
| `lastHeartbeatAt` | timestamp | ✅ | Last strategy heartbeat. |
| `lastDecisionAt` | timestamp | ⛔ | Last signal/decision timestamp. |
| `lastOrderAt` | timestamp | ⛔ | Last order placed (if applicable). |
| `positionsCount` | number | ⛔ | Summary. |
| `exposureUsd` | number | ⛔ | Summary. |
| `pnlDayUsd` | number | ⛔ | Summary. |
| `pnlTotalUsd` | number | ⛔ | Summary. |
| `riskState` | string | ⛔ | Enum: `normal`, `limited`, `halted`. |
| `killSwitchEnabled` | boolean | ⛔ | Server-evaluated. |
| `links` | map | ⛔ | Logs/metrics/runbook. |
| `labels` | map | ⛔ | Team/subsystem/etc. |
| `meta` | map | ⛔ | Free-form. |

### Indexed fields

- **Single-field (default)**: `status`, `updatedAt`, `lastHeartbeatAt`, `mode`
- If you plan to query “by status + updatedAt” frequently, add a composite index (optional; not required by current request).

### Suggested realtime query patterns

- Strategy overview: `orderBy displayName`
- “Needs attention”: `where status in ["error","paused"]` + `orderBy updatedAt desc` (may require index if combined)

---

## 3) `ingest_pipelines/{pipelineId}`

Represents ingestion pipelines (Pub/Sub subscriptions, streaming connectors, backfills) with lag and health status.

### Document ID strategy

- **Recommended**: stable ID derived from pipeline name + environment.
  - Examples: `pubsub.market_ingest.dev`, `pubsub.options_ingest.prod`, `congressional_ingest.prod`

### Fields

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `pipelineId` | string | ✅ | Must equal document ID. |
| `displayName` | string | ✅ | UI-friendly. |
| `status` | string | ✅ | Enum: `healthy`, `degraded`, `down`, `unknown`, `maintenance`. |
| `updatedAt` | timestamp | ✅ | Server write time for latest material change. |
| `lastSeenAt` | timestamp | ✅ | Last time pipeline processed/observed activity. |
| `lagSeconds` | number | ✅ | End-to-end lag estimate. |
| `throughputPerMin` | number | ⛔ | Observed rate. |
| `errorRatePerMin` | number | ⛔ | Observed rate. |
| `dlqDepth` | number | ⛔ | If DLQ exists. |
| `source` | string | ⛔ | e.g. `alpaca`, `polygon`, `sec_filings`. |
| `subscription` | string | ⛔ | Pub/Sub subscription name (or logical). |
| `region` | string | ⛔ | Runtime region. |
| `environment` | string | ⛔ | dev/staging/prod. |
| `links` | map | ⛔ | Logs/metrics. |
| `labels` | map | ⛔ | Low-cardinality tags. |
| `meta` | map | ⛔ | Free-form. |

### Indexed fields

- **Composite (required for dashboard query)**: `status`, `lagSeconds`
- **Single-field (default)**: `lastSeenAt`, `updatedAt`, `lagSeconds`, `dlqDepth`, `environment`, `region`

### Suggested realtime query patterns

- “Most lagged degraded pipelines”: `where status == "degraded"` + `orderBy lagSeconds desc`

---

## 4) `ops_alerts/{alertId}`

Represents deduplicated operational alerts (not individual events). Designed for upsert based on a stable fingerprint.

### Document ID strategy

- **Recommended**: deterministic fingerprint to enable idempotent upserts and deduping.
  - Pattern: `{source}__{kind}__{entityType}__{entityId}__{fingerprintHash}`
  - Example: `ingest__dlq_depth__pipeline__pubsub.market_ingest.prod__c0a80123`
- **Avoid** purely random IDs (harder to dedupe/upsert from streams).

### Fields

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `alertId` | string | ✅ | Must equal document ID. |
| `title` | string | ✅ | Short summary. |
| `severity` | string | ✅ | Enum: `info`, `warning`, `error`, `critical`. |
| `state` | string | ✅ | Enum: `open`, `acked`, `resolved`, `suppressed`. |
| `firstSeenAt` | timestamp | ✅ | When alert fingerprint first appeared. |
| `lastSeenAt` | timestamp | ✅ | Updated whenever the alert is observed again. |
| `updatedAt` | timestamp | ✅ | Server write time for latest material change. |
| `source` | string | ✅ | e.g. `strategy_engine`, `ingest`, `execution_engine`. |
| `kind` | string | ✅ | e.g. `stale_heartbeat`, `error_burst`, `dlq_depth`. |
| `entityType` | string | ⛔ | `service`, `strategy`, `pipeline`, etc. |
| `entityId` | string | ⛔ | References the corresponding doc ID. |
| `message` | string | ⛔ | Human-readable detail (keep bounded). |
| `count` | number | ⛔ | Increment on repeated occurrences. |
| `dedupeKey` | string | ✅ | Stable fingerprint input (may equal `alertId`). |
| `ack` | map | ⛔ | `{ byUid, byEmail, at, note }` if acked. |
| `resolution` | map | ⛔ | `{ at, reason }` if resolved/suppressed. |
| `labels` | map | ⛔ | Low-cardinality tags (team, runbook). |
| `meta` | map | ⛔ | Structured context for drilldown (avoid high-cardinality indexed fields). |

### Indexed fields

- **Composite (required for dashboard query)**: `severity`, `state`, `lastSeenAt`
- **Single-field (default)**: `updatedAt`, `lastSeenAt`, `firstSeenAt`, `severity`, `state`, `source`, `kind`

### Suggested realtime query patterns

- Active alerts: `where state in ["open","acked"]` + `orderBy lastSeenAt desc` (index may be required depending on exact filters)
- Triage view: `where severity in ["error","critical"]` + `where state == "open"` + `orderBy lastSeenAt desc`

---

## Optional subcollections (recommended)

These are designed for **bounded, TTL-managed** drilldown without bloating the primary documents.

### `.../{doc}/recent_errors/{errorId}` (collection group: `recent_errors`)

- Recommended for `ops_services`, `ops_strategies`, and `ingest_pipelines`.
- `errorId` strategy: `{timestampMillis}_{shortHash}` to avoid hot-spotting and preserve ordering.

Suggested fields:

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `seenAt` | timestamp | ✅ | When this error instance was observed. |
| `message` | string | ✅ | Short detail. |
| `code` | string | ⛔ | Error code/class. |
| `stack` | string | ⛔ | Keep bounded; consider truncation. |
| `source` | string | ⛔ | Component name. |
| `fingerprint` | string | ⛔ | Hash for grouping. |
| `expiresAt` | timestamp | ✅ | TTL field (see `firestore_ttl.md`). |
| `meta` | map | ⛔ | Structured context. |

### `ingest_pipelines/{pipelineId}/sampled_dlq/{messageId}` (optional)

Store a low-volume sample of DLQ messages for debugging.

Suggested fields:

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `receivedAt` | timestamp | ✅ | When sampled. |
| `payload` | map/string | ✅ | Sample payload (sanitize secrets/PII). |
| `attributes` | map | ⛔ | Pub/Sub attributes. |
| `deliveryAttempt` | number | ⛔ | If available. |
| `expiresAt` | timestamp | ✅ | TTL field. |

---

## 5) `ops_agents/{agentId}` (Agent Registry)

Represents a **centralized agent registry entry** with:

- **metadata** (identity/ownership/runtime coordinates)
- **capabilities**
- **lifecycle mode/state** (observe/shadow/paper + disabled/emergency stop)
- **health status** (heartbeat-driven)

This is intended as a **server-written read model** (similar to `ops_services`) for an ops dashboard and control plane.

### Document ID strategy

- **Recommended**: `{environment}.{agentName}`
  - Examples: `prod.strategy-engine`, `prod.execution-service`, `prod.marketdata-mcp-server`

### Fields

| Field | Type | Required | Notes |
|---|---:|:---:|---|
| `agentId` | string | ✅ | Must equal document ID. |
| `displayName` | string | ✅ | UI-friendly. |
| `kind` | string | ✅ | Enum: `service`, `strategy`, `execution`, `worker`, `cron`. |
| `environment` | string | ✅ | `dev`, `staging`, `prod`. |
| `capabilities` | map | ✅ | Boolean flags (e.g. `can_execute_paper`, `can_publish_heartbeats`). |
| `lifecycle` | map | ✅ | Contains desired/observed/effective lifecycle states + audit fields. |
| `health` | map | ✅ | Health enum + heartbeat timestamps. |
| `owner` | map | ⛔ | `{ team, oncall, runbookUrl }`. |
| `runtime` | map | ⛔ | `{ platform, region, namespace, workload, instanceId }`. |
| `version` | map | ⛔ | `{ gitSha, imageTag, buildTime }`. |
| `labels` | map | ⛔ | Low-cardinality tags. |
| `meta` | map | ⛔ | Free-form server metadata. |
| `createdAt` | timestamp | ✅ | Server timestamp. |
| `updatedAt` | timestamp | ✅ | Server write time for latest material change. |

Recommended `lifecycle` fields:

- `desiredState`: enum `registered`, `observing`, `shadow_active`, `paper_active`, `disabled`, `emergency_stop`
- `observedState`: same enum (best-effort from heartbeats)
- `effectiveState`: computed enum after kill-switch/safety overlay
- `lastTransitionAt`, `lastDesiredChangeAt`: timestamps
- `changedBy`: `{ actorType, actorId, actorEmail, ticket }`

Recommended `health` fields:

- `status`: enum `healthy`, `degraded`, `down`, `unknown`
- `lastHeartbeatAt`: timestamp
- `reasonCodes`: array of strings (bounded)
- `links`: `{ logs, metrics, runbook }`

### Indexed fields

- **Composite**: `lifecycle.effectiveState`, `updatedAt`
- **Composite**: `health.status`, `health.lastHeartbeatAt`
- **Single-field (default)**: `updatedAt`, `environment`, `kind`

### Optional subcollections (recommended)

#### `ops_agents/{agentId}/events/{eventId}` (collection group: `events`)

Append-only transition/audit history (bounded via TTL).

Suggested fields:

- `at` (timestamp), `type` (string), `fromState` (string), `toState` (string), `actor` (map), `reason` (string), `meta` (map), `expiresAt` (timestamp)

