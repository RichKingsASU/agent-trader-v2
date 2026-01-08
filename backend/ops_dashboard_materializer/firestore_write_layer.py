from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from backend.common.logging import log_event
from backend.persistence.firebase_client import get_firestore_client

from backend.ops_dashboard_materializer.models import as_dt, normalize_keys

logger = logging.getLogger("ops_dashboard_materializer")

try:
    # google-cloud-firestore provides the transactional decorator used by firebase_admin's client.
    from google.cloud.firestore_v1 import transactional  # type: ignore
except Exception:  # pragma: no cover
    transactional = None  # type: ignore[assignment]

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _short_hash_id(obj: Any) -> str:
    """
    Deterministic, compact doc id based on stable JSON encoding.

    Returns 32 hex chars (128 bits) to avoid extremely long IDs.
    """
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]

def _truncate_str(value: Any, *, max_len: int) -> str:
    s = "" if value is None else str(value)
    if max_len <= 0:
        return ""
    return s if len(s) <= max_len else (s[: max_len - 1] + "…")


def _sanitize_payload(value: Any) -> Any:
    """
    Best-effort scrub for secrets/PII in sampled DLQ docs.
    """
    SENSITIVE_KEYS = {
        "authorization",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "client_secret",
    }
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k).lower()
            if ks in SENSITIVE_KEYS:
                out[str(k)] = "[redacted]"
            else:
                out[str(k)] = _sanitize_payload(v)
        return out
    if isinstance(value, list):
        return [_sanitize_payload(v) for v in value[:50]]
    return value


def deterministic_alert_id(payload: dict[str, Any]) -> str:
    """
    Deterministic alert doc id.

    Preference order:
    - alertId / id / dedupeKey / fingerprint from payload
    - otherwise: hash(entityRef + (type/title/code/reason) + severity)

    NOTE: We intentionally do NOT include `state` so open/ack/resolved updates map to one doc.
    """
    for k in ("alertId", "id", "dedupeKey", "fingerprint"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    entity_ref = payload.get("entityRef")
    severity = payload.get("severity")
    typ = payload.get("type") or payload.get("title") or payload.get("code") or payload.get("reason") or "unknown"
    basis = {"entityRef": entity_ref, "type": typ, "severity": severity}
    return _short_hash_id(basis)


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _newer(a: Optional[datetime], b: Optional[datetime]) -> bool:
    """
    True if `a` is strictly newer than `b`.
    Missing `b` means `a` wins. Missing `a` means it loses.
    """
    if a is None:
        return False
    if b is None:
        return True
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a.astimezone(timezone.utc) > b.astimezone(timezone.utc)


def _max_dt(*values: Any) -> Optional[datetime]:
    """
    Best-effort max() over datetime-ish values (datetime / RFC3339 string / Firestore Timestamp-as-datetime).
    """
    ds: list[datetime] = []
    for v in values:
        dt = as_dt(v)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ds.append(dt.astimezone(timezone.utc))
    return max(ds) if ds else None


OPS_SERVICE_STATUSES = ("healthy", "degraded", "down", "unknown", "maintenance")
OpsServiceStatus = str


def normalize_ops_service_status(raw: Any) -> tuple[OpsServiceStatus, str]:
    """
    Normalize many producer/status variants to the canonical ops_services.status enum.

    Back-compat friendly: unknown values map to "unknown" but raw is preserved for debugging.
    """
    raw_s = "" if raw is None else str(raw)
    s = raw_s.strip().lower()
    if not s:
        return "unknown", raw_s

    # Common "healthy" aliases
    if s in {"ok", "okay", "healthy", "running", "up", "online", "alive", "serving", "ready"}:
        return "healthy", raw_s

    # Common "degraded" aliases
    if s in {"degraded", "warn", "warning", "partial", "slow", "lagging"}:
        return "degraded", raw_s

    # Common "down" aliases
    if s in {"down", "offline", "error", "failed", "failure", "fatal", "critical", "unhealthy", "crashloop"}:
        return "down", raw_s

    # Maintenance-ish
    if s in {"maintenance", "maint", "draining", "paused", "pause"}:
        return "maintenance", raw_s

    # Unknown-ish
    if s in {"unknown", "n/a", "na", "none", "null", "undefined", "?"}:
        return "unknown", raw_s

    # Pass through already-canonical values
    if s in set(OPS_SERVICE_STATUSES):
        return s, raw_s

    return "unknown", raw_s


def is_ops_service_transition_allowed(prev: OpsServiceStatus, nxt: OpsServiceStatus) -> bool:
    """
    Validate status transitions for ops_services.

    Key invariant for ops dashboard UX:
    - "unknown → degraded → healthy" must be allowed.
    - prevent known -> unknown clobbering (unknown treated as "no signal").
    """
    p, n = (prev or "unknown"), (nxt or "unknown")
    if n == p:
        return True
    if p in {"healthy", "degraded", "down", "maintenance"} and n == "unknown":
        return False
    # Otherwise, allow (time ordering/stale protection handles safety).
    return True


@dataclass(frozen=True)
class SourceInfo:
    topic: str
    subscription: str
    messageId: str
    publishedAt: datetime


class FirestoreWriteLayer:
    """
    Firestore projection writer (latest state only).

    All methods are at-least-once safe and ordering-agnostic (stale event rejection).
    """

    def __init__(self, *, project_id: Optional[str] = None) -> None:
        self._db = get_firestore_client(project_id=project_id)

    def write_sampled_dlq_event(
        self,
        *,
        message_id: Optional[str],
        subscription: Optional[str],
        delivery_attempt: Optional[int],
        http_status: int,
        reason: str,
        error: str,
        kind: Optional[str],
        attributes: Optional[dict[str, str]],
        payload: Any,
        ttl_hours: float,
    ) -> Optional[str]:
        """
        Best-effort: write a sampled DLQ-candidate record into Firestore.

        Retention is bounded via `expiresAt` (TTL field; enable TTL on collection group `sampled_dlq`).
        """
        try:
            hours = float(ttl_hours)
        except Exception:
            hours = 72.0
        if hours <= 0:
            return None

        now = _utc_now()
        msg_id = (message_id or "").strip()
        doc_id = msg_id or _short_hash_id({"ts": now.isoformat(), "subscription": subscription or "", "reason": reason})
        ref = self._db.collection("sampled_dlq").document(doc_id)

        safe_payload = _sanitize_payload(payload)
        payload_json = ""
        try:
            payload_json = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            payload_json = ""
        max_payload_chars = 24_000
        payload_too_large = bool(payload_json) and (len(payload_json) > max_payload_chars)

        doc: dict[str, Any] = {
            "messageId": msg_id,
            "subscription": (subscription or "").strip(),
            "kind": (kind or "").strip(),
            "httpStatus": int(http_status),
            "reason": _truncate_str(reason, max_len=256),
            "error": _truncate_str(error, max_len=2048),
            "deliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
            "attributes": dict(attributes or {}),
            "receivedAt": now,
            "expiresAt": now + timedelta(hours=hours),
        }

        if not payload_too_large:
            doc["payload"] = safe_payload
            doc["payloadTruncated"] = False
        elif payload_json:
            doc["payloadJsonSnippet"] = _truncate_str(payload_json, max_len=max_payload_chars)
            doc["payloadTruncated"] = True

        doc = {k: v for k, v in doc.items() if v is not None and v != ""}
        try:
            ref.set(doc, merge=False)
            return doc_id
        except Exception as e:
            log_event(logger, "dlq.sample_write_failed", severity="WARNING", error=str(e), message_id=msg_id)
            return None

    def write_ops_service_latest(
        self,
        *,
        service_id: str,
        status: str,
        last_heartbeat_at: Optional[datetime],
        version: str,
        region: str,
        instance_count: Optional[int],
        source: SourceInfo,
    ) -> Tuple[bool, str]:
        """
        Writes `ops_services/{serviceId}`.

        Returns: (applied, reason)
        """
        ref = self._db.collection("ops_services").document(service_id)

        if transactional is None:
            raise RuntimeError("google-cloud-firestore transactional decorator unavailable")

        @transactional
        def _txn(txn) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_source = (existing or {}).get("source") if isinstance(existing, dict) else None
            existing_source_pub = existing_source.get("publishedAt") if isinstance(existing_source, dict) else None
            existing_eff = _max_dt(
                (existing or {}).get("lastHeartbeatAt") if isinstance(existing, dict) else None,
                (existing or {}).get("last_heartbeat_at") if isinstance(existing, dict) else None,
                (existing or {}).get("updatedAt") if isinstance(existing, dict) else None,
                (existing or {}).get("updated_at") if isinstance(existing, dict) else None,
                existing_source_pub,
            )

            incoming_eff = _max_dt(last_heartbeat_at, source.publishedAt)
            if existing_eff is not None and incoming_eff is not None and incoming_eff < existing_eff:
                return False, "stale_event_ignored"

            prev_status, _ = normalize_ops_service_status((existing or {}).get("status") if isinstance(existing, dict) else None)
            next_status, raw_status = normalize_ops_service_status(status)
            if not is_ops_service_transition_allowed(prev_status, next_status):
                next_status = prev_status
            # Treat unknown as "no signal": do not clobber a known status.
            if next_status == "unknown" and prev_status != "unknown":
                next_status = prev_status

            doc = {
                "serviceId": str(service_id),
                "service_id": str(service_id),
                "status": str(next_status),
                "status_raw": str(raw_status),
                # Back-compat: keep both snake_case and camelCase timestamp fields.
                "lastHeartbeatAt": last_heartbeat_at,
                "last_heartbeat_at": last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                "instanceCount": int(instance_count) if instance_count is not None else None,
                "updatedAt": incoming_eff or _utc_now(),
                "updated_at": incoming_eff or _utc_now(),
                "source": {
                    "topic": source.topic,
                    "subscription": source.subscription,
                    "messageId": source.messageId,
                    "publishedAt": source.publishedAt,
                },
            }
            # Overwrite to keep the read model strict (no drift / no extra fields).
            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

    def write_ops_strategy_latest(
        self,
        *,
        strategy_id: str,
        mode: str,
        status: str,
        last_decision_at: Optional[datetime],
        last_heartbeat_at: Optional[datetime],
        effective_at: Optional[datetime],
    ) -> Tuple[bool, str]:
        """
        Writes `ops_strategies/{strategyId}`.

        Stale check uses `effective_at` (best-effort) against existing max(lastDecisionAt,lastHeartbeatAt).
        """
        ref = self._db.collection("ops_strategies").document(strategy_id)

        if transactional is None:
            raise RuntimeError("google-cloud-firestore transactional decorator unavailable")

        @transactional
        def _txn(txn) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_ld = as_dt((existing or {}).get("lastDecisionAt") if isinstance(existing, dict) else None)
            existing_lh = as_dt((existing or {}).get("lastHeartbeatAt") if isinstance(existing, dict) else None)
            existing_eff = max([d for d in (existing_ld, existing_lh) if d is not None], default=None)

            if effective_at is not None and not _newer(effective_at, existing_eff):
                return False, "stale_event_ignored"

            doc = {
                "mode": str(mode),
                "status": str(status),
                "lastDecisionAt": last_decision_at,
                "lastHeartbeatAt": last_heartbeat_at,
            }
            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

    def write_ingest_pipeline_latest(
        self,
        *,
        pipeline_id: str,
        status: str,
        lag_seconds: Optional[float],
        throughput_per_min: Optional[float],
        error_rate_per_min: Optional[float],
        last_success_at: Optional[datetime],
        last_error_at: Optional[datetime],
        last_event_at: Optional[datetime],
    ) -> Tuple[bool, str]:
        """
        Writes `ingest_pipelines/{pipelineId}`.

        Stale check uses lastEventAt.
        """
        ref = self._db.collection("ingest_pipelines").document(pipeline_id)

        if transactional is None:
            raise RuntimeError("google-cloud-firestore transactional decorator unavailable")

        @transactional
        def _txn(txn) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}
            existing_le = as_dt((existing or {}).get("lastEventAt") if isinstance(existing, dict) else None)

            if last_event_at is not None and not _newer(last_event_at, existing_le):
                return False, "stale_event_ignored"

            doc = {
                "status": str(status),
                "lagSeconds": float(lag_seconds) if lag_seconds is not None else None,
                "throughputPerMin": float(throughput_per_min) if throughput_per_min is not None else None,
                "errorRatePerMin": float(error_rate_per_min) if error_rate_per_min is not None else None,
                "lastSuccessAt": last_success_at,
                "lastErrorAt": last_error_at,
                "lastEventAt": last_event_at,
            }
            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

    def upsert_ops_alert_latest(
        self,
        *,
        alert_id: str,
        severity: str,
        state: str,
        entity_ref: Any,
        published_at: Optional[datetime],
    ) -> Tuple[bool, str]:
        """
        Upserts `ops_alerts/{alertId}`.

        - deterministic IDs ensure idempotency
        - firstSeenAt set once
        - lastSeenAt updated only if newer
        """
        ref = self._db.collection("ops_alerts").document(alert_id)
        incoming = published_at or _utc_now()
        if incoming.tzinfo is None:
            incoming = incoming.replace(tzinfo=timezone.utc)

        if transactional is None:
            raise RuntimeError("google-cloud-firestore transactional decorator unavailable")

        @transactional
        def _txn(txn) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_last = as_dt((existing or {}).get("lastSeenAt") if isinstance(existing, dict) else None)
            if existing_last is not None and not _newer(incoming, existing_last):
                return False, "stale_event_ignored"

            first_seen = (existing or {}).get("firstSeenAt") if isinstance(existing, dict) else None
            if not isinstance(first_seen, datetime):
                first_seen = incoming

            doc = {
                "severity": str(severity),
                "state": str(state),
                "entityRef": entity_ref,
                "firstSeenAt": first_seen,
                "lastSeenAt": incoming,
            }
            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

    # ---- parsing helpers (best-effort, schemaVersion aware) ----

    def extract_ops_service_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        p = normalize_keys(payload)
        return {
            "serviceId": p.get("serviceId") or p.get("service"),
            "status": p.get("status"),
            "lastHeartbeatAt": as_dt(p.get("lastHeartbeatAt")),
            "version": p.get("version") or "",
            "region": p.get("region") or "",
            "instanceCount": _coerce_int(p.get("instanceCount")),
        }

    def extract_ops_strategy_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        p = normalize_keys(payload)
        last_decision_at = as_dt(p.get("lastDecisionAt"))
        last_heartbeat_at = as_dt(p.get("lastHeartbeatAt"))
        effective_at = max([d for d in (last_decision_at, last_heartbeat_at) if d is not None], default=None)
        return {
            "strategyId": p.get("strategyId") or p.get("strategy"),
            "mode": p.get("mode") or "",
            "status": p.get("status") or "",
            "lastDecisionAt": last_decision_at,
            "lastHeartbeatAt": last_heartbeat_at,
            "effectiveAt": effective_at,
        }

    def extract_ingest_pipeline_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        p = normalize_keys(payload)
        return {
            "pipelineId": p.get("pipelineId") or p.get("pipeline"),
            "status": p.get("status") or "",
            "lagSeconds": _coerce_float(p.get("lagSeconds")),
            "throughputPerMin": _coerce_float(p.get("throughputPerMin")),
            "errorRatePerMin": _coerce_float(p.get("errorRatePerMin")),
            "lastSuccessAt": as_dt(p.get("lastSuccessAt")),
            "lastErrorAt": as_dt(p.get("lastErrorAt")),
            "lastEventAt": as_dt(p.get("lastEventAt")),
        }

    def extract_ops_alert_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        p = normalize_keys(payload)
        alert_id = deterministic_alert_id(p)
        return {
            "alertId": alert_id,
            "severity": p.get("severity") or "info",
            "state": p.get("state") or "open",
            "entityRef": p.get("entityRef"),
        }


def log_write_outcome(
    *,
    kind: str,
    doc_id: str,
    applied: bool,
    reason: str,
    subscription: Optional[str],
    message_id: Optional[str],
) -> None:
    log_event(
        logger,
        "materializer.write",
        severity="INFO" if applied else "NOTICE",
        kind=str(kind),
        doc_id=str(doc_id),
        applied=bool(applied),
        reason=str(reason),
        subscription=subscription,
        message_id=message_id,
    )

