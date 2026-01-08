## Replay & Backfill Strategy (Design Only)

**Objective**: Safely replay/backfill **Firestore read models** derived from **canonical Pub/Sub events**, under **at-least-once** delivery, using **idempotent writes**, while minimizing UI disruption.

**Assumptions**

- **Pub/Sub is canonical** (source of truth is the event stream).
- **Firestore is derived state** (query-optimized read model).
- Delivery is **at-least-once** and can be **out-of-order** unless explicitly enforced.
- Projectors/writers are **idempotent** (same event processed twice is safe).

---

## Design Principles

- **Determinism**: The read model must be reproducible from the same event set and projection code.
- **Idempotency + monotonicity**: Ignore duplicates and reject stale/out-of-order updates using a monotonic cursor per aggregate.
- **Isolation**: Replays should run on dedicated infra (subscriptions, service accounts, rate limits) and never compete with live processing.
- **Safe cutover**: Backfill into a versioned read model, validate, then switch via an indirection pointer/flag (blue/green).
- **Auditability**: Every replay/backfill run must be attributable (run id), bounded (time window), and reversible (no destructive writes during build).

---

## Canonical Event Contract (Minimum Requirements)

To make replay/backfill safe and predictable, events should carry (or be derivable to) these fields:

- **`event_id`**: globally unique (UUID/ULID). Used for dedupe/audit.
- **`event_type`**: stable name (e.g. `shadow_trade.opened`).
- **`schema_version`**: integer or semver for the event payload schema.
- **`occurred_at`**: authoritative event time (RFC3339 / timestamp).
- **`ingested_at`**: when the system accepted the event (optional but helpful).
- **`tenant_id`** and **`uid`** (or equivalent partition keys).
- **`aggregate_type`** and **`aggregate_id`**: the entity whose state the event mutates.
- **`sequence`**: **monotonic per aggregate** (recommended). If present, it is the primary guard against out-of-order updates.

If `sequence` is not available, you can still replay, but reconciliation becomes harder and projections must be commutative or rely on compensating logic.

---

## Firestore Read Model Versioning (Avoid UI Disruption)

### Versioned collections

Write derived state into versioned paths, e.g.:

- `users/{uid}/shadowTradeHistory_v1/{tradeId}`
- `users/{uid}/shadowTradeHistory_v2/{tradeId}`

or tenant-scoped equivalents:

- `tenants/{tenantId}/readmodels/v1/...`
- `tenants/{tenantId}/readmodels/v2/...`

### Indirection pointer for cutover

Maintain a small document that UI (and APIs) consult to select which version to read:

- `ops/read_model_pointers/current`:
  - `active_version`: `"v1"` | `"v2"`
  - `ramp`: optional per-tenant/per-user overrides
  - `updated_at`, `updated_by`, `run_id`

**Cutover is an atomic pointer change**, not a bulk rewrite of existing documents. This prevents UI disruption and enables fast rollback.

### Compatibility window

During migration, keep the UI able to read both versions (or implement a thin “read facade” service that reads the active version). Avoid breaking queries/index requirements mid-flight.

---

## Replay Paths: Reprocess Retained Events

### Path A — “Within retention” replay via Pub/Sub seek (preferred for recent windows)

Use a **dedicated replay subscription** on the canonical topic:

- Replay sub uses **message retention** and (optionally) **retain acknowledged messages**.
- Replay sub is isolated from live consumer sub(s) to prevent reprocessing storms.

To reprocess a time window:

- **Seek subscription** to a timestamp (or snapshot) at/near window start.
- Consume until window end, then stop the job.

Notes:

- Seeking is fast and avoids re-publishing events.
- If your canonical stream is not strictly ordered, use `sequence`/cursor guards in the projector.

### Path B — “Beyond retention” replay from an event archive (required for true backfill)

Pub/Sub message retention is finite; for backfills older than retention you need an **event archive**:

- **GCS archive**: append-only NDJSON/Parquet partitioned by date/topic/tenant.
- **BigQuery archive**: immutable table partitioned by ingestion time (and clustered by `tenant_id`, `aggregate_id`).

Backfill options from the archive:

- **Direct project**: a backfill job reads archived events and applies projections to Firestore (no Pub/Sub).
- **Re-publish**: backfill job republishes to a **replay topic**, and replay workers consume from it. This keeps one projection pipeline.

Recommendation:

- Use **direct project** for large historical backfills (lower cost, fewer moving parts).
- Use **re-publish** when you must reuse existing “live” consumer logic with minimal divergence.

---

## Idempotent Projection Pattern (Core Safety Mechanism)

### Per-aggregate cursor guard

Store a cursor on each read-model aggregate document:

- `projection.cursor.sequence` (or `projection.cursor.occurred_at`)
- `projection.cursor.event_id`
- `projection.cursor.updated_at`
- `projection.cursor.run_id` (optional; useful during backfills)

**Write rule** (conceptual):

- If incoming `sequence` <= stored `sequence`: **ignore** (duplicate or stale).
- Else: apply mutation and update cursor atomically.

Implement cursor comparison and state updates in a Firestore **transaction** to avoid concurrent write races between live processing and replay/backfill workers.

### Dedupe cache (optional)

If you have rare “same sequence but different event_id” scenarios (shouldn’t happen), maintain an `events_applied` subcollection keyed by `event_id` with TTL. Use it sparingly to avoid write amplification.

---

## Reconciling Firestore With Reality (Detect + Repair)

### What “reality” means

Reality is the canonical event stream (Pub/Sub + archive). Firestore is correct iff applying the canonical events using the current projection code yields exactly the stored read model (within defined tolerances).

### Reconciliation modes

- **Audit-only (recommended default)**:
  - Recompute expected state for a bounded scope (tenant/user/time window).
  - Compare to Firestore (field-by-field or hash-based).
  - Emit a discrepancy report (BigQuery table or GCS report artifact).
- **Repair-in-place (high risk)**:
  - Apply corrective writes to the active read model.
  - Only safe for narrowly-scoped, well-understood defects.
- **Repair-by-rebuild (recommended for non-trivial issues)**:
  - Build a new versioned read model (v2), validate, then cut over via pointer.

### Comparison strategies

- **Hash comparison**:
  - Compute a stable canonical JSON representation of expected document state.
  - Store `projection.state_hash` in Firestore for fast mismatch detection.
- **Invariant checks**:
  - E.g., “sum of child positions equals account total”, “OPEN trades have `closed_at` unset”, “timestamps monotonic”.
- **Sampling + full**:
  - Start with statistical sampling to estimate blast radius, then run full validation when needed.

---

## Schema Evolution Strategy (Events + Read Models)

### Event schema evolution (canonical)

- Keep events **backward compatible** where possible (additive fields).
- Use explicit **`schema_version`** in each event.
- Maintain **upcasters**:
  - Transform older event versions into the current in-memory shape before projecting.

Rules:

- **Never** change meaning of an existing field without bumping version and providing an upcaster.
- **Avoid** relying on Firestore document schema as canonical; always derive from events.

### Read model evolution (derived)

Prefer **versioned read models** over in-place migrations when:

- Queries/indexes change.
- Document shape changes materially.
- You need a safe UI cutover with rollback.

Use in-place migrations only when:

- Changes are additive and non-breaking.
- You can tolerate partial rollout without query/index changes.

---

## Avoiding UI Disruption During Replay/Backfill

### Don’t replay into the active model (by default)

Default posture:

- Backfill into **new version (v2)**, validate, then flip pointer.

### Protect UI performance and consistency

- **Rate limit** Firestore writes (global and per-document) to avoid contention.
- **Batch writes** when safe, but keep per-aggregate cursor logic transactional.
- **Index readiness**:
  - Pre-deploy Firestore composite indexes needed by v2 queries before cutover.
- **Graceful read fallback**:
  - For a limited window, if v2 doc missing, read v1 (or show “loading historical data”).
- **Per-tenant ramp**:
  - Enable v2 for internal tenants first; gradually ramp to all tenants.

### Live + replay concurrency

If live processing must continue during backfill:

- Use cursor guards so replay cannot overwrite newer state.
- Consider temporarily routing live events to **both** v1 and v2 (dual projection) for the overlap window, then stop v1 after cutover.

---

## Recommended Cloud Run Jobs

These are “jobs” (finite workloads) rather than long-lived services. All jobs should support:

- `--run-id` (required), `--dry-run`, `--tenant-id`, `--uid` (optional scope filters)
- `--start`, `--end` (time window), `--max-qps`, `--max-outstanding`
- structured logs + metrics

### 1) `readmodel-replay-worker` (Pub/Sub → Firestore, windowed)

**Purpose**: Consume from a replay subscription (or replay topic) and apply idempotent projections into a target read model version.

- Inputs: `--subscription`, `--target-version`, `--start`, `--end`
- Behavior: stop once the window is fully processed (time-bounded) and lag is near zero.
- Safety: enforces cursor guards; supports `--pause-live` mode only if explicitly requested.

### 2) `readmodel-backfill-from-archive` (Archive → Firestore, bulk)

**Purpose**: Backfill older-than-retention history from GCS/BigQuery into Firestore read model v2.

- Inputs: `--source=gcs|bq`, `--prefix`/`--query`, `--target-version`
- Behavior: parallelizes by tenant/date partitions; checkpoints progress.
- Safety: strictly bounded scope; emits progress artifacts and discrepancy counts.

### 3) `readmodel-reconcile` (Audit discrepancies)

**Purpose**: Recompute expected state from canonical events and compare against Firestore.

- Outputs: discrepancy report (BigQuery table or GCS JSON report).
- Modes: `--audit-only` (default), `--emit-repair-plan` (no writes).

### 4) `readmodel-cutover` (Pointer flip + ramp control)

**Purpose**: Atomically change `ops/read_model_pointers/current` to activate v2 for a subset or all tenants.

- Inputs: `--activate-version=v2`, optional `--tenant-allowlist`, `--ramp-percent`
- Safety: validates index readiness + basic doc presence before enabling.

### 5) `readmodel-schema-migrate` (Optional in-place additive migration)

**Purpose**: Apply additive schema changes to the active model (only when safe).

- Inputs: `--collection-group`, `--field-additions`, `--where` filters
- Safety: rate limited, resumable, and produces a change report.

### 6) `readmodel-cleanup-old-versions` (Garbage collect)

**Purpose**: Delete or TTL old read model versions after stabilization.

- Safety: only after a freeze period; must support “list-only” and “delete-confirmation” modes.

---

## Safety Guardrails (Must-Haves)

### Guardrail A — Replay isolation

- Dedicated replay subscription(s) and service account.
- Separate Cloud Run job for replay with lower resource limits and explicit throttles.

### Guardrail B — Scope bounding

Every run requires explicit scope:

- time window (`--start/--end`) AND at least one of:
  - `--tenant-id` allowlist, or
  - `--uid` allowlist, or
  - `--max-tenants` (for controlled batch processing)

### Guardrail C — Rate limiting + contention controls

- Global write QPS cap (`--max-qps`)
- Per-aggregate concurrency cap (avoid hot documents)
- Backoff on `RESOURCE_EXHAUSTED` and contention errors

### Guardrail D — Idempotency enforced by code, not by hope

- Cursor guard in a transaction for every aggregate update.
- “Duplicate event processed” must be a normal, logged-at-debug event, not an error.

### Guardrail E — Dry-run and audit artifacts

Mandatory modes:

- `--dry-run`: compute intended writes, do not write.
- `--audit-only`: reconcile without mutation.

Artifacts to emit per run:

- counts: events read, events applied, duplicates ignored, stale ignored, errors
- lag metrics and throughput
- discrepancy report (if reconcile)

### Guardrail F — Kill switch

Central kill-switch document (pattern consistent with existing repo safety posture):

- `ops/killswitch/readmodel_replay` with fields:
  - `enabled: bool`
  - `reason: string`
  - `updated_at`

All jobs check it on startup and periodically.

### Guardrail G — Safe cutover + rollback

- Cutover only via pointer flip.
- Rollback is pointer flip back to v1.
- Keep v1 available for a defined stabilization window.

---

## Suggested Operational Runbooks (High-Level)

### Runbook 1: Reprocess last N hours (within retention)

- Create/verify replay subscription on canonical topic.
- Seek replay subscription to `start`.
- Run `readmodel-replay-worker` targeting `v2` (or `v1` only if explicitly approved).
- Run `readmodel-reconcile --audit-only` for the same window.
- If acceptable, cut over via `readmodel-cutover` (optional).

### Runbook 2: Backfill older history (beyond retention)

- Ensure event archive coverage for target dates.
- Run `readmodel-backfill-from-archive` into `v2` (bounded by tenant/time).
- Validate via `readmodel-reconcile` (sampling, then full if needed).
- Predeploy indexes required for v2 queries.
- Cut over via pointer flip and ramp.

---

## Notes on Firestore Cost/Scale

Replays can be write-heavy. Keep these practices:

- Prefer **rebuild into v2** over in-place corrections for complex changes.
- Partition and parallelize by **tenant/date**.
- Use **batching** for independent documents, but keep per-aggregate cursor updates transactional.
- Monitor Firestore usage dashboards during runs; auto-throttle when nearing limits.

---

## Deliverables Summary

- **This doc**: `replay_backfill.md`
- **Recommended Cloud Run jobs**: replay worker, archive backfill, reconcile, cutover, schema migrate, cleanup
- **Safety guardrails**: isolation, scope bounds, throttling, transactional cursors, dry-run/audit artifacts, kill switch, pointer-based cutover/rollback

