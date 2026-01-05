from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def tenants_collection():
    db = get_firestore_client()
    return db.collection("tenants")


def tenant_doc(*, tenant_id: str):
    db = get_firestore_client()
    return db.collection("tenants").document(tenant_id)


def tenant_subcollection(*, tenant_id: str, name: str):
    return tenant_doc(tenant_id=tenant_id).collection(name)


def accounts_collection(*, tenant_id: str):
    return tenant_subcollection(tenant_id=tenant_id, name="accounts")


def strategies_collection(*, tenant_id: str):
    return tenant_subcollection(tenant_id=tenant_id, name="strategies")


def runs_collection(*, tenant_id: str):
    return tenant_subcollection(tenant_id=tenant_id, name="runs")


def ledger_trades_collection(*, tenant_id: str):
    return tenant_subcollection(tenant_id=tenant_id, name="ledger_trades")


def stable_trade_id(
    *,
    tenant_id: str,
    account_id: Optional[str],
    broker_fill_id: Optional[str],
    order_id: Optional[str],
    ts: Any,
    symbol: str,
) -> str:
    """
    Best-effort deterministic id for idempotent ingestion.

    Prefer providing a broker-native fill id; otherwise we hash a tuple of stable fields.
    """
    if broker_fill_id:
        return str(broker_fill_id)
    s = "|".join(
        [
            str(tenant_id or ""),
            str(account_id or ""),
            str(order_id or ""),
            str(ts or ""),
            str(symbol or ""),
        ]
    )
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def append_ledger_trade(*, tenant_id: str, trade_id: str, payload: dict[str, Any]) -> None:
    """
    Append-only write to tenants/{tenant_id}/ledger_trades/{trade_id}.

    This uses Firestore's `create()` to ensure immutability semantics (fails if doc exists).
    """
    if payload.get("tenant_id") not in (None, tenant_id):
        raise ValueError("payload.tenant_id must match tenant_id")

    doc = dict(payload)
    doc["tenant_id"] = tenant_id
    doc.setdefault("created_at", _utc_now())

    # `create` fails if document already exists -> append-only.
    with_firestore_retry(lambda: ledger_trades_collection(tenant_id=tenant_id).document(trade_id).create(doc))

