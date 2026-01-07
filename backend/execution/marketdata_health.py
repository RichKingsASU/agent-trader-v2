from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if hasattr(value, "to_datetime"):
        try:
            dt = value.to_datetime()
            if isinstance(dt, datetime):
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


@dataclass(frozen=True)
class MarketDataHeartbeat:
    path: str
    exists: bool
    last_heartbeat_at: datetime | None
    age_seconds: float | None
    is_stale: bool
    status: str | None = None


def check_market_ingest_heartbeat(
    *,
    tenant_id: str | None,
    stale_threshold_seconds: int = 120,
) -> MarketDataHeartbeat:
    """
    Checks the market ingest heartbeat document written by ingestion:
      - tenants/{tenant_id}/ops/market_ingest (preferred when tenant_id is known)
      - ops/market_ingest (legacy/global)

    Fail-safe behavior:
      - Any read/parsing error => is_stale=True
      - Missing doc/ts => is_stale=True
    """
    threshold = int(stale_threshold_seconds)
    now = _utc_now()

    try:
        from backend.persistence.firebase_client import get_firestore_client

        db = get_firestore_client()
        if tenant_id:
            doc_ref = db.collection("tenants").document(str(tenant_id)).collection("ops").document("market_ingest")
            path = f"tenants/{tenant_id}/ops/market_ingest"
        else:
            doc_ref = db.collection("ops").document("market_ingest")
            path = "ops/market_ingest"

        doc = doc_ref.get()
        if not doc.exists:
            return MarketDataHeartbeat(
                path=path,
                exists=False,
                last_heartbeat_at=None,
                age_seconds=None,
                is_stale=True,
                status=None,
            )

        data = doc.to_dict() or {}
        ts = _coerce_dt(data.get("ts") or data.get("last_heartbeat") or data.get("last_heartbeat_at"))
        if ts is None:
            return MarketDataHeartbeat(
                path=path,
                exists=True,
                last_heartbeat_at=None,
                age_seconds=None,
                is_stale=True,
                status=str(data.get("status") or "") or None,
            )

        age_s = (now - ts).total_seconds()
        is_stale = age_s > threshold
        return MarketDataHeartbeat(
            path=path,
            exists=True,
            last_heartbeat_at=ts,
            age_seconds=age_s,
            is_stale=is_stale,
            status=str(data.get("status") or "") or None,
        )
    except Exception as e:
        logger.warning("marketdata_health.heartbeat_check_failed: %s", e)
        return MarketDataHeartbeat(
            path=f"tenants/{tenant_id}/ops/market_ingest" if tenant_id else "ops/market_ingest",
            exists=False,
            last_heartbeat_at=None,
            age_seconds=None,
            is_stale=True,
            status=None,
        )

