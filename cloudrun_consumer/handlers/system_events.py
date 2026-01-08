from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
import traceback
from typing import Any, Optional

from cloudrun_consumer.firestore_writer import SourceInfo
from cloudrun_consumer.replay_support import ReplayContext
from cloudrun_consumer.time_audit import ensure_utc

def _as_utc(dt: datetime) -> datetime:
    return ensure_utc(dt, source="cloudrun_consumer.handlers.system_events._as_utc", field="dt")


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="cloudrun_consumer.handlers.system_events._parse_ts", field="datetime")
    # allow epoch millis for compatibility if encountered
    if isinstance(value, (int, float)):
        try:
            return _as_utc(datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc))
        except Exception:
            try:
                sys.stderr.write(
                    json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "severity": "ERROR",
                            "event_type": "system_events.parse_ts_epoch_failed",
                            "value_type": type(value).__name__,
                            "exception": traceback.format_exc()[-8000:],
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sys.stderr.flush()
            except Exception:
                pass
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return ensure_utc(dt, source="cloudrun_consumer.handlers.system_events._parse_ts", field="iso_string")
    except Exception:
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "event_type": "system_events.parse_ts_iso_failed",
                        "value": s[:256],
                        "exception": traceback.format_exc()[-8000:],
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
        return None


def _status_from_severity(severity: str) -> str:
    s = (severity or "").strip().upper()
    if s in {"DEBUG", "INFO", "NOTICE"}:
        return "healthy"
    if s in {"WARNING", "WARN"}:
        return "degraded"
    if s in {"ERROR", "CRITICAL", "ALERT", "EMERGENCY", "FATAL"}:
        return "down"
    return "unknown"


def handle_system_event(
    *,
    payload: dict[str, Any],
    env: str,
    default_region: str,
    source_topic: str,
    message_id: str,
    pubsub_published_at: datetime,
    firestore_writer: Any,
    replay: ReplayContext | None = None,
) -> dict[str, Any]:
    """
    Materialize `SystemEventPayload` into `ops_services/{serviceId}`.
    """
    service_id = str(payload.get("service") or "").strip()
    if not service_id:
        raise ValueError("missing_service")

    # If producedAt/publishedAt is present in the payload, it must be parseable.
    produced_at_raw = payload.get("producedAt")
    published_at_raw = payload.get("publishedAt")
    produced_at = _parse_ts(produced_at_raw) if "producedAt" in payload else None
    published_at = _parse_ts(published_at_raw) if "publishedAt" in payload else None
    if "producedAt" in payload and produced_at is None:
        raise ValueError("invalid_producedAt")
    if "publishedAt" in payload and published_at is None:
        raise ValueError("invalid_publishedAt")

    last_heartbeat_at = _parse_ts(payload.get("timestamp"))
    # For system events, the event's own timestamp is the best ordering signal.
    updated_at = produced_at or published_at or last_heartbeat_at or _as_utc(pubsub_published_at)

    severity = str(payload.get("severity") or "")
    status = _status_from_severity(severity)

    version = (
        str(payload.get("version") or "").strip()
        or str(payload.get("sha") or "").strip()
        or str(payload.get("git_sha") or "").strip()
        or "unknown"
    )

    region = str(payload.get("region") or "").strip() or str(default_region or "").strip() or "unknown"

    source = SourceInfo(
        topic=str(source_topic),
        message_id=str(message_id),
        published_at=ensure_utc(pubsub_published_at, source="cloudrun_consumer.handlers.system_events.handle_system_event", field="pubsub_published_at"),
    )

    # Best-effort stable key for replay-mode dedupe.
    # Prefer a producer-issued eventId if present; otherwise fall back to a tuple-ish key.
    replay_key = None
    if isinstance(payload.get("eventId"), str) and str(payload.get("eventId")).strip():
        replay_key = str(payload.get("eventId")).strip()
    else:
        replay_key = f"{env}__{service_id}__{updated_at.isoformat()}"

    applied, reason = firestore_writer.dedupe_and_upsert_ops_service(
        message_id=str(message_id),
        replay=replay,
        replay_dedupe_key=replay_key,
        service_id=service_id,
        env=str(env or "unknown"),
        status=status,
        last_heartbeat_at=last_heartbeat_at,
        version=version,
        region=region,
        updated_at=updated_at,
        source=source,
    )

    return {
        "kind": "ops_services",
        "serviceId": service_id,
        "applied": bool(applied),
        "reason": str(reason),
        "status": status,
        "updatedAt": updated_at.isoformat(),
    }

