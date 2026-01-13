from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _short_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def try_write_contract_violation_alert(
    *,
    topic: str,
    producer: Optional[str],
    event_type: Optional[str],
    message: str,
    errors: list[dict[str, Any]],
    sample: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Best-effort write into Firestore `ops_alerts/{alertId}` for contract violations.

    This is intentionally defensive:
    - never raises
    - writes only if a project id is available
    - keeps payload small
    """
    project_id = (
        (os.getenv("FIRESTORE_PROJECT_ID") or "").strip()
        or (os.getenv("GCP_PROJECT") or "").strip()
        or (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    )
    if not project_id:
        return None

    # Safety: never write to production Firestore from local execution unless explicitly allowed.
    try:
        from backend.persistence.firebase_client import is_local_execution  # local import to avoid cycles
    except Exception:
        is_local_execution = None  # type: ignore[assignment]
    if is_local_execution is not None and is_local_execution():
        if not (os.getenv("FIRESTORE_EMULATOR_HOST") or "").strip() and (os.getenv("ALLOW_PROD_FIRESTORE") or "").strip() != "1":
            return None

    try:
        from google.cloud import firestore  # type: ignore
    except Exception:
        return None

    now = _utc_now()
    alert_id = _short_hash(
        {
            "kind": "pubsub_contract_violation",
            "topic": str(topic),
            "producer": str(producer or ""),
            "event_type": str(event_type or ""),
            "message": str(message),
            "errors": errors[:10],
        }
    )

    doc: dict[str, Any] = {
        "severity": "error",
        "state": "open",
        "type": "pubsub_contract_violation",
        "title": "Pub/Sub contract violation",
        "entityRef": {"topic": str(topic), "producer": producer, "eventType": event_type},
        "message": str(message)[:512],
        "firstSeenAt": now,
        "lastSeenAt": now,
        "details": {"errors": errors[:25], "sample": sample or {}},
    }

    try:
        db = firestore.Client(project=project_id)
        db.collection("ops_alerts").document(alert_id).set(doc, merge=True)
        return alert_id
    except Exception:
        return None

