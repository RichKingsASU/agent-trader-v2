from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339_best_effort(value: Any) -> Optional[datetime]:
    """
    Best-effort RFC3339 parser for timestamps found in Pub/Sub payloads.

    Accepts:
    - datetime (returned as UTC, tz-aware)
    - ISO strings with Z or +00:00, etc.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


MaterializerKind = Literal["ops_services", "ops_strategies", "ingest_pipelines", "ops_alerts"]


@dataclass(frozen=True)
class RouteConfig:
    """
    Maps a Pub/Sub subscription to a materialized Firestore read model.

    `topic` is required for ops_services to populate the mandatory `source.topic` field.
    """

    subscription: str
    kind: MaterializerKind
    topic: Optional[str] = None


@dataclass(frozen=True)
class PubSubEnvelope:
    """
    Normalized input for the materializer.

    This is intentionally minimal: Pub/Sub is canonical; Firestore stores projections only.
    """

    payload: Any
    attributes: dict[str, str]
    message_id: Optional[str]
    publish_time_utc: Optional[datetime]
    subscription: Optional[str]


def schema_version_from(payload: Any, attributes: dict[str, str]) -> int:
    """
    Determine schemaVersion (default=1) from attributes or payload.
    """
    candidates: list[Any] = []
    for k in ("schemaVersion", "schema_version", "schema_version_int"):
        if k in attributes:
            candidates.append(attributes.get(k))
    if isinstance(payload, dict):
        for k in ("schemaVersion", "schema_version", "schema_version_int"):
            if k in payload:
                candidates.append(payload.get(k))
    for v in candidates:
        if v is None:
            continue
        try:
            return max(1, int(str(v).strip()))
        except Exception:
            continue
    return 1


def translate_payload_forward(*, schema_version: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Translate older payload variants forward into the canonical shape this materializer expects.

    This does NOT redesign producer contracts; it only performs conservative, best-effort key normalization.
    """
    v = max(1, int(schema_version or 1))
    # Current canonical version is v1 for this materializer.
    # For older versions/missing version, treat the same and normalize keys.
    _ = v  # reserved for future version-specific translations
    return normalize_keys(payload)


def normalize_keys(d: dict[str, Any]) -> dict[str, Any]:
    """
    Translate common legacy key variants to the canonical camelCase keys used by Firestore read models.
    """
    out = dict(d)

    renames = {
        # identity
        "service_id": "serviceId",
        "strategy_id": "strategyId",
        "pipeline_id": "pipelineId",
        # timestamps
        "last_heartbeat_at": "lastHeartbeatAt",
        "last_decision_at": "lastDecisionAt",
        "last_success_at": "lastSuccessAt",
        "last_error_at": "lastErrorAt",
        "last_event_at": "lastEventAt",
        # ingest metrics
        "lag_seconds": "lagSeconds",
        "throughput_per_min": "throughputPerMin",
        "error_rate_per_min": "errorRatePerMin",
    }
    for old, new in renames.items():
        if old in out and new not in out:
            out[new] = out.get(old)
    return out


def as_dt(value: Any) -> Optional[datetime]:
    return _parse_rfc3339_best_effort(value)

