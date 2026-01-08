from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from time_audit import ensure_utc


_DOC_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-:.]+")


def as_utc(dt: datetime) -> datetime:
    return ensure_utc(dt, source="cloudrun_consumer.event_utils.as_utc", field="dt")


def parse_ts(value: Any) -> Optional[datetime]:
    """
    Parses timestamps commonly found in Pub/Sub payloads:
    - RFC3339/ISO8601 strings (with or without Z)
    - epoch millis (int/float)
    - datetime objects
    Returns an aware UTC datetime or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="cloudrun_consumer.event_utils.parse_ts", field="datetime")
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except Exception:
            try:
                sys.stderr.write(
                    json.dumps(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "severity": "ERROR",
                            "event_type": "event_utils.parse_ts_epoch_failed",
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
        return ensure_utc(dt, source="cloudrun_consumer.event_utils.parse_ts", field="iso_string")
    except Exception:
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "event_type": "event_utils.parse_ts_iso_failed",
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


def ordering_ts(*, payload: dict[str, Any], pubsub_published_at: datetime) -> datetime:
    """
    Ordering preference for event streams:
    - producedAt (best)
    - publishedAt
    - timestamp/ts/time (fallbacks if producers vary)
    - Pub/Sub publish time (last resort)
    """
    produced_at = parse_ts(payload.get("producedAt")) if "producedAt" in payload else None
    published_at = parse_ts(payload.get("publishedAt")) if "publishedAt" in payload else None
    ts = parse_ts(payload.get("timestamp")) or parse_ts(payload.get("ts")) or parse_ts(payload.get("time"))
    return produced_at or published_at or ts or ensure_utc(pubsub_published_at, source="cloudrun_consumer.event_utils.ordering_ts", field="pubsub_published_at")


def choose_doc_id(*, payload: dict[str, Any], message_id: str) -> str:
    """
    Deterministic Firestore doc id:
    - eventId if present and non-empty
    - else Pub/Sub messageId
    """
    event_id = payload.get("eventId") if isinstance(payload, dict) else None
    candidate = str(event_id).strip() if event_id is not None else ""
    if not candidate:
        candidate = str(message_id or "").strip()
    return normalize_doc_id(candidate)


def normalize_doc_id(value: str) -> str:
    """
    Firestore doc ids cannot contain '/', and very long ids are inconvenient.
    This keeps ids stable + reasonably readable, while remaining deterministic.
    """
    v = (value or "").strip()
    if not v:
        return "unknown"
    v = v.replace("/", "_")
    v = _DOC_ID_SAFE_RE.sub("_", v)
    v = re.sub(r"_{2,}", "_", v).strip("_")
    # Firestore doc id limit is 1500 bytes; keep far below that.
    return v[:256] if len(v) > 256 else v


def infer_topic(
    *,
    attributes: dict[str, str],
    payload: dict[str, Any],
    subscription: str | None,
) -> Optional[str]:
    """
    Best-effort topic inference for Pub/Sub push deliveries.
    Prefer explicit attributes/payload hints; optionally fall back to an env mapping:
      SUBSCRIPTION_TOPIC_MAP='{"my-sub":"market-ticks"}'
    """
    for k in ("topic", "pubsubTopic", "sourceTopic"):
        v = attributes.get(k)
        if v and str(v).strip():
            return str(v).strip()
        pv = payload.get(k)
        if isinstance(pv, str) and pv.strip():
            return pv.strip()

    sub = (subscription or "").strip()
    if not sub:
        return None
    sub_name = sub.split("/")[-1]

    raw = os.getenv("SUBSCRIPTION_TOPIC_MAP") or ""
    if not raw.strip():
        return None
    try:
        mapping = json.loads(raw)
    except Exception:
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "event_type": "event_utils.subscription_topic_map_parse_failed",
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
    if not isinstance(mapping, dict):
        return None
    mapped = mapping.get(sub_name)
    return str(mapped).strip() if isinstance(mapped, str) and mapped.strip() else None

