from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from google.cloud import firestore

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
    }
    # Optional correlation identifiers for joinability across stages.
    for k in ("correlation_id", "signal_id", "allocation_id", "execution_id"):
        if logical_order.get(k) is not None:
            raw[k] = logical_order.get(k)
    return raw


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
