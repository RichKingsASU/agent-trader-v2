from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from google.cloud import firestore
from google.api_core import exceptions as gexc

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry

from .models import PaperOrderCreate, PaperOrder


COLLECTION_PAPER_ORDERS = "paper_orders"


def get_db():
    return get_firestore_client()


def build_raw_order(logical_order: dict) -> dict:
    """
    Build the broker-facing payload (raw_order).
    For now it's just a mirror of the logical order + metadata.
    """
    raw = {
        "instrument_type": logical_order["instrument_type"],
        "symbol": logical_order["symbol"],
        "side": logical_order["side"],
        "order_type": logical_order["order_type"],
        "time_in_force": logical_order.get("time_in_force", "day"),
        "notional": logical_order["notional"],
        "quantity": logical_order.get("quantity"),
        "strategy_id": logical_order["strategy_id"],
        "broker_account_id": logical_order["broker_account_id"],
        "uid": logical_order["uid"],
        "idempotency_key": logical_order.get("idempotency_key"),
    }
    # Optional correlation identifiers for joinability across stages.
    for k in ("correlation_id", "signal_id", "allocation_id", "execution_id"):
        if logical_order.get(k) is not None:
            raw[k] = logical_order.get(k)
    return raw


def _stable_order_uuid(*, idempotency_key: str) -> UUID:
    """
    Deterministic UUID derived from an idempotency key.

    This enables idempotent inserts by using Firestore `create()` on a stable doc id.
    """
    return uuid5(NAMESPACE_URL, str(idempotency_key))


def insert_paper_order(*, tenant_id: str, payload: PaperOrderCreate) -> PaperOrder:
    """
    Persist a paper order in Firestore and return the stored record.

    Firestore schema:
      tenants/{tenant_id}/paper_orders/{uuid}
        - user_id (str)
        - broker_account_id (str)
        - strategy_id (str)
        - ... (order fields)
        - created_at (timestamp)
    """
    db = get_db()
    idem_key = None
    try:
        idem_key = (payload.raw_order or {}).get("idempotency_key")
    except Exception:
        idem_key = None
    order_id = _stable_order_uuid(idempotency_key=str(idem_key)) if idem_key else uuid4()
    created_at_dt = datetime.now(timezone.utc)

    doc = {
        "id": str(order_id),
        "correlation_id": payload.correlation_id,
        "signal_id": payload.signal_id,
        "allocation_id": payload.allocation_id,
        "execution_id": payload.execution_id,
        "uid": str(payload.uid),
        "broker_account_id": str(payload.broker_account_id),
        "strategy_id": str(payload.strategy_id),
        "symbol": payload.symbol,
        "instrument_type": payload.instrument_type,
        "side": payload.side,
        "order_type": payload.order_type,
        "time_in_force": payload.time_in_force,
        "notional": payload.notional,
        "quantity": payload.quantity,
        "risk_allowed": payload.risk_allowed,
        "risk_scope": payload.risk_scope,
        "risk_reason": payload.risk_reason,
        "raw_order": payload.raw_order,
        "status": payload.status,
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_at_iso": created_at_dt.isoformat(),
    }

    ref = (
        db.collection("tenants")
        .document(tenant_id)
        .collection(COLLECTION_PAPER_ORDERS)
        .document(str(order_id))
    )
    try:
        with_firestore_retry(lambda: ref.create(doc))
    except gexc.AlreadyExists:
        snap = with_firestore_retry(lambda: ref.get())
        existing = snap.to_dict() if snap.exists else {}
        created_at = str((existing or {}).get("created_at_iso") or created_at_dt.isoformat())
        return PaperOrder(
            id=UUID(str((existing or {}).get("id") or str(order_id))),
            created_at=created_at,
            uid=str((existing or {}).get("uid") or payload.uid),
            broker_account_id=UUID(str((existing or {}).get("broker_account_id") or str(payload.broker_account_id))),
            strategy_id=UUID(str((existing or {}).get("strategy_id") or str(payload.strategy_id))),
            symbol=str((existing or {}).get("symbol") or payload.symbol),
            instrument_type=str((existing or {}).get("instrument_type") or payload.instrument_type),
            side=str((existing or {}).get("side") or payload.side),
            order_type=str((existing or {}).get("order_type") or payload.order_type),
            time_in_force=str((existing or {}).get("time_in_force") or payload.time_in_force),
            notional=float((existing or {}).get("notional") or payload.notional),
            quantity=(existing or {}).get("quantity") if (existing or {}).get("quantity") is not None else payload.quantity,
            risk_allowed=bool(
                (existing or {}).get("risk_allowed")
                if (existing or {}).get("risk_allowed") is not None
                else payload.risk_allowed
            ),
            risk_scope=(existing or {}).get("risk_scope") or payload.risk_scope,
            risk_reason=(existing or {}).get("risk_reason") or payload.risk_reason,
            raw_order=(existing or {}).get("raw_order") or payload.raw_order,
            status=str((existing or {}).get("status") or payload.status),
        )

    # Return an API-friendly shape (match existing model expectations).
    return PaperOrder(
        id=UUID(str(order_id)),
        created_at=created_at_dt.isoformat(),
        correlation_id=payload.correlation_id,
        signal_id=payload.signal_id,
        allocation_id=payload.allocation_id,
        execution_id=payload.execution_id,
        uid=payload.uid,
        broker_account_id=payload.broker_account_id,
        strategy_id=payload.strategy_id,
        symbol=payload.symbol,
        instrument_type=payload.instrument_type,
        side=payload.side,
        order_type=payload.order_type,
        time_in_force=payload.time_in_force,
        notional=payload.notional,
        quantity=payload.quantity,
        risk_allowed=payload.risk_allowed,
        risk_scope=payload.risk_scope,
        risk_reason=payload.risk_reason,
        raw_order=payload.raw_order,
        status=payload.status,
    )


def insert_paper_order_idempotent(
    *, tenant_id: str, payload: PaperOrderCreate, idempotency_key: str
) -> PaperOrder:
    """
    Restart-safe/idempotent variant of insert_paper_order.

    Behavior:
    - Deterministically derives the Firestore doc id from idempotency_key (UUIDv5).
    - Uses Firestore `create()` so the first writer wins; retries return the existing doc.

    This provides "no duplicate orders / no double notional" safety across retries and restarts,
    without changing the broader storage model.
    """
    from backend.common.idempotency import stable_uuid_from_key

    db = get_db()
    order_id = stable_uuid_from_key(key=f"{tenant_id}:paper_order:{idempotency_key}")
    created_at_dt = datetime.now(timezone.utc)

    doc = {
        "id": str(order_id),
        "uid": str(payload.uid),
        "broker_account_id": str(payload.broker_account_id),
        "strategy_id": str(payload.strategy_id),
        "symbol": payload.symbol,
        "instrument_type": payload.instrument_type,
        "side": payload.side,
        "order_type": payload.order_type,
        "time_in_force": payload.time_in_force,
        "notional": payload.notional,
        "quantity": payload.quantity,
        "risk_allowed": payload.risk_allowed,
        "risk_scope": payload.risk_scope,
        "risk_reason": payload.risk_reason,
        "raw_order": payload.raw_order,
        "status": payload.status,
        "idempotency_key": str(idempotency_key),
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_at_iso": created_at_dt.isoformat(),
    }

    ref = (
        db.collection("tenants")
        .document(tenant_id)
        .collection(COLLECTION_PAPER_ORDERS)
        .document(str(order_id))
    )

    try:
        with_firestore_retry(lambda: ref.create(doc))
        stored = doc
    except AlreadyExists:
        snap = with_firestore_retry(lambda: ref.get())
        stored = snap.to_dict() or doc

    return PaperOrder(
        id=UUID(str(stored.get("id") or order_id)),
        created_at=str(stored.get("created_at_iso") or created_at_dt.isoformat()),
        uid=str(stored.get("uid") or payload.uid),
        broker_account_id=UUID(str(stored.get("broker_account_id") or payload.broker_account_id)),
        strategy_id=UUID(str(stored.get("strategy_id") or payload.strategy_id)),
        symbol=str(stored.get("symbol") or payload.symbol),
        instrument_type=str(stored.get("instrument_type") or payload.instrument_type),
        side=str(stored.get("side") or payload.side),
        order_type=str(stored.get("order_type") or payload.order_type),
        time_in_force=str(stored.get("time_in_force") or payload.time_in_force),
        notional=float(stored.get("notional") or payload.notional),
        quantity=(float(stored.get("quantity")) if stored.get("quantity") is not None else payload.quantity),
        risk_allowed=bool(stored.get("risk_allowed") if stored.get("risk_allowed") is not None else payload.risk_allowed),
        risk_scope=stored.get("risk_scope") or payload.risk_scope,
        risk_reason=stored.get("risk_reason") or payload.risk_reason,
        raw_order=dict(stored.get("raw_order") or payload.raw_order),
        status=str(stored.get("status") or payload.status),
    )
