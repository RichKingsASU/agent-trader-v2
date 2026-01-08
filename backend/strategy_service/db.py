from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists

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
    return {
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
    }


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
    order_id = uuid4()
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
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_at_iso": created_at_dt.isoformat(),
    }

    with_firestore_retry(
        lambda: db.collection("tenants")
        .document(tenant_id)
        .collection(COLLECTION_PAPER_ORDERS)
        .document(str(order_id))
        .set(doc, merge=False)
    )

    # Return an API-friendly shape (match existing model expectations).
    return PaperOrder(
        id=UUID(str(order_id)),
        created_at=created_at_dt.isoformat(),
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
