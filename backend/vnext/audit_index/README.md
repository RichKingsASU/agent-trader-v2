# Unified Audit Artifact Index (Audit-first Scaffolding)

This package defines a **unified index** for audit artifacts across vNEXT.

It is **contracts-only** (schemas + interfaces). There is intentionally **no**
storage implementation here.

## Core principles

- **Evidence > opinions**
  - An audit record should point to concrete evidence: a log line, a payload, a
    trace/span, a snapshot, or an immutable document.
  - Prefer **structured** evidence (JSON) and include `content_hash` when
    possible for tamper-evidence.

- **Append-only**
  - Audit artifacts are **never edited in place**.
  - Corrections are made by writing a **new artifact** that references the prior
    one (via `correlation_id`, `subject`, and/or `metadata`).
  - This package therefore exposes **no update/delete** interfaces.

## What is an "artifact"?

An artifact is an immutable piece of audit evidence or decision context, indexed
by metadata so it can be discovered later.

Artifact categories (`ArtifactType`):

- **LOG**: Operational evidence (structured logs, trace exports, metric snapshots).
- **DECISION**: A recorded decision/proposal with inputs/outputs/versions.
- **OVERRIDE**: Human/policy overrides (who/why/what).
- **EVENT**: Domain/system events (state transitions, alerts, triggers).

## Public contracts

See `interfaces.py`:

- `AuditArtifact`: immutable metadata record (points to evidence via `evidence_uri`)
- `RetentionPolicy`: retention metadata (TTL / holds / rationale)
- `AuditArtifactIndex.list_artifacts(filter)`: read-only query interface

## Non-goals

- Implementing storage (Firestore/SQL/GCS/etc.)
- Enforcing retention (that belongs to lifecycle/ops tooling)
- Defining an execution workflow (vNEXT is OBSERVE-only by default per `backend/vnext/GOVERNANCE.md`)

