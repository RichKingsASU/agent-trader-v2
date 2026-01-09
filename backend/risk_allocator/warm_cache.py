from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry

logger = logging.getLogger(__name__)


class WarmCacheError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        return float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _read_alpaca_snapshot_doc(
    *,
    db=None,
    user_id: str = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    """
    Warm-cache read for account snapshot fields (buying power, equity, etc).

    Multi-tenant path: users/{user_id}/alpacaAccounts/snapshot
    Falls back to legacy global path: alpacaAccounts/snapshot
    """
    client = db or get_firestore_client()

    def _get():
        if user_id:
            return client.collection("users").document(user_id).collection("alpacaAccounts").document("snapshot").get()
        logger.warning(
            "Using legacy global alpacaAccounts/snapshot path. Provide user_id for multi-tenant support."
        )
        return client.collection("alpacaAccounts").document("snapshot").get()

    snap = with_firestore_retry(_get)
    if require_exists and not snap.exists:
        path = f"users/{user_id}/alpacaAccounts/snapshot" if user_id else "alpacaAccounts/snapshot"
        raise WarmCacheError(f"Missing warm-cache snapshot at Firestore doc {path}")
    return snap.to_dict() or {}


def get_warm_cache_buying_power_usd(
    *,
    db=None,
    user_id: str = None,
    max_age_s: Optional[float] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Returns (buying_power_usd, snapshot_dict).

    Safety behavior:
    - If snapshot is missing, stale, or buying_power <= 0 => returns 0 and logs a warning.
    """
    if max_age_s is None:
        max_age_s = float(os.getenv("ALPACA_SNAPSHOT_MAX_AGE_S", "300"))

    try:
        snap = _read_alpaca_snapshot_doc(db=db, user_id=user_id, require_exists=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("Warm-cache read failed; forcing buying_power=0: %s", e)
        return 0.0, {}

    buying_power = _as_float(snap.get("buying_power"))
    if buying_power <= 0:
        logger.warning("Warm-cache buying_power <= 0 (buying_power=%s); forcing flat", buying_power)
        return 0.0, snap

    updated_at_iso = (snap.get("updated_at_iso") or "").strip() if isinstance(snap.get("updated_at_iso"), str) else ""
    if updated_at_iso:
        try:
            updated_at = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
            age_s = max(0.0, (_utc_now() - updated_at).total_seconds())
            if max_age_s is not None and age_s > max_age_s:
                logger.warning(
                    "Warm-cache snapshot is stale (age_s=%.1f > max_age_s=%.1f); forcing flat",
                    age_s,
                    max_age_s,
                )
                return 0.0, snap
        except Exception:  # noqa: BLE001
            logger.warning("Warm-cache updated_at_iso unparseable; forcing flat")
            return 0.0, snap

    return buying_power, snap

