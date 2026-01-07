"""
Unified Audit Artifact Index (contracts only).

This module defines *append-only* audit artifact metadata and a minimal query
interface. It is intentionally:
- contracts-only (no storage, no I/O, no network calls)
- evidence-first (records point to concrete evidence: logs, payloads, traces)
- append-only (no update/delete interfaces; new evidence is additive)

Audit artifacts exist to answer: "What happened, when, and based on what evidence?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class ArtifactType(str, Enum):
    """
    High-level artifact category.

    - LOG: Raw operational output (structured logs, traces, metrics snapshots).
    - DECISION: A recorded decision/proposal (inputs, outputs, versions, rationale).
    - OVERRIDE: Human or policy override (who/why/what changed).
    - EVENT: A domain/system event (state transitions, alerts, triggers).
    """

    LOG = "log"
    DECISION = "decision"
    OVERRIDE = "override"
    EVENT = "event"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """
    Retention policy for an audit artifact.

    Notes:
    - Retention is metadata. Enforcement is implemented outside this module.
    - `legal_hold=True` indicates retention should not expire automatically.
    - `expires_at` should be timezone-aware (recommended: UTC) when set.
    """

    policy_name: str
    expires_at: datetime | None = None
    legal_hold: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AuditArtifact:
    """
    Immutable index record for one audit artifact.

    This record should reference *evidence* (content) via `evidence_uri` and
    optionally provide `content_hash` for tamper-evidence.

    Fields:
    - `artifact_id`: Stable unique ID for the index entry.
    - `artifact_type`: High-level category (LOG/DECISION/OVERRIDE/EVENT).
    - `created_at`: When the artifact was emitted/recorded (timezone-aware recommended).
    - `evidence_uri`: Location of the underlying evidence (e.g., GCS/S3 path, DB key).
    - `content_hash`: Optional hash (e.g., sha256 hex) of the evidence payload.
    - `retention`: Retention metadata (TTL/holds/etc.).
    - `tenant_id`: Optional tenancy scope.
    - `correlation_id`: Optional cross-system trace/correlation key.
    - `actor`: Optional "who" (service, user, job, agent id).
    - `subject`: Optional "what" (order id, strategy id, account id, entity id).
    - `metadata`: Freeform structured metadata for filtering/explainability.
    """

    artifact_id: str
    artifact_type: ArtifactType
    created_at: datetime

    evidence_uri: str
    content_hash: str | None = None
    retention: RetentionPolicy = field(default_factory=lambda: RetentionPolicy(policy_name="default"))

    tenant_id: str | None = None
    correlation_id: str | None = None
    actor: str | None = None
    subject: str | None = None

    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuditArtifactFilter:
    """
    Filter for listing audit artifacts.

    Notes:
    - All fields are optional. Implementations may enforce additional constraints.
    - `limit` is advisory; implementations may clamp to safe bounds.
    - `cursor` is an opaque pagination token.
    """

    tenant_id: str | None = None
    artifact_type: ArtifactType | None = None
    correlation_id: str | None = None
    actor: str | None = None
    subject: str | None = None

    created_at_gte: datetime | None = None
    created_at_lte: datetime | None = None

    limit: int = 100
    cursor: str | None = None


@runtime_checkable
class AuditArtifactIndex(Protocol):
    """
    Read-only interface for querying audit artifact metadata.

    Governance invariant:
    - Listing is safe and side-effect free; mutation/persistence live elsewhere.
    """

    def list_artifacts(self, filter: AuditArtifactFilter) -> Sequence[AuditArtifact]:
        """
        List artifacts matching the given filter.

        Implementations should return results in a stable order (recommended:
        reverse-chronological by `created_at`) and honor pagination via `cursor`.
        """

