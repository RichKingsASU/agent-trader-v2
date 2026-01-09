from __future__ import annotations

"""
Atomic, race-safe capital reservation.

Why this exists:
- Multiple strategies/agents can attempt to spend the same buying power concurrently.
- Any "check then update" sequence is race-prone in distributed systems.

This module provides:
- Pure state transition helpers (`apply_reserve`, `apply_release`) with strict assertions:
  - cannot reserve twice (same trade_id with a different amount, or after release)
  - cannot release more than reserved
  - reservation is idempotent by trade_id (re-reserve same amount is a no-op)
- Firestore-backed atomic wrappers that apply those transitions inside a single
  Firestore transaction.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

try:
    from firebase_admin import firestore as admin_firestore  # type: ignore
except Exception:  # pragma: no cover
    # Keep pure helpers importable in minimal/test environments.
    admin_firestore = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class CapitalReservationError(RuntimeError):
    """Base error for capital reservation violations."""


class DuplicateReservationError(CapitalReservationError):
    """Raised when a trade_id is reserved twice in a non-idempotent way."""


class InsufficientBuyingPowerError(CapitalReservationError):
    """Raised when reserving would exceed available buying power."""


class ReleaseError(CapitalReservationError):
    """Raised when release is invalid (missing reservation, over-release, etc.)."""


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return Decimal("0")
        return Decimal(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TradeReservation:
    trade_id: str
    amount_usd: Decimal
    state: str  # "reserved" | "released"
    reserved_at: datetime
    released_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "amount_usd": str(self.amount_usd),
            "state": self.state,
            "reserved_at": self.reserved_at,
            "released_at": self.released_at,
        }


@dataclass(frozen=True)
class CapitalReservationState:
    """
    Snapshot of reservation state for a single (tenant_id, uid, broker_account_id).
    """

    reserved_total_usd: Decimal
    reservations: Dict[str, TradeReservation]  # trade_id -> reservation

    @staticmethod
    def empty() -> "CapitalReservationState":
        return CapitalReservationState(reserved_total_usd=Decimal("0"), reservations={})


def apply_reserve(
    *,
    state: CapitalReservationState,
    trade_id: str,
    amount_usd: Decimal,
    buying_power_usd: Optional[Decimal] = None,
    now: Optional[datetime] = None,
) -> Tuple[CapitalReservationState, TradeReservation]:
    """
    Pure transition: reserve amount_usd for trade_id.

    Assertions:
    - Idempotent by trade_id: reserving the same amount twice is a no-op.
    - Cannot reserve twice with a different amount.
    - Cannot reserve a trade_id after it has been released.
    - Cannot reserve such that reserved_total exceeds buying_power_usd (if provided).
    """
    trade_id = str(trade_id or "").strip()
    if not trade_id:
        raise ValueError("trade_id is required")
    if amount_usd <= 0:
        raise ValueError("amount_usd must be > 0")
    now = now or _utc_now()

    existing = state.reservations.get(trade_id)
    if existing is not None:
        if existing.state == "reserved":
            if existing.amount_usd != amount_usd:
                raise DuplicateReservationError(
                    f"trade_id {trade_id} already reserved for {existing.amount_usd}, cannot reserve {amount_usd}"
                )
            # Idempotent success: keep state unchanged.
            return state, existing
        # existing.state == "released" (or anything else)
        raise DuplicateReservationError(f"trade_id {trade_id} was already released; cannot reserve again")

    new_total = state.reserved_total_usd + amount_usd
    if buying_power_usd is not None and new_total > buying_power_usd:
        raise InsufficientBuyingPowerError(
            f"insufficient buying power: attempting to reserve {amount_usd} would make reserved_total "
            f"{new_total} > buying_power {buying_power_usd}"
        )

    reservation = TradeReservation(
        trade_id=trade_id,
        amount_usd=amount_usd,
        state="reserved",
        reserved_at=now,
        released_at=None,
    )
    new_reservations = dict(state.reservations)
    new_reservations[trade_id] = reservation
    return CapitalReservationState(reserved_total_usd=new_total, reservations=new_reservations), reservation


def apply_release(
    *,
    state: CapitalReservationState,
    trade_id: str,
    now: Optional[datetime] = None,
) -> Tuple[CapitalReservationState, TradeReservation]:
    """
    Pure transition: release the full reserved amount for trade_id.

    Assertions:
    - Cannot release if no reservation exists.
    - Idempotent by trade_id: releasing twice is a no-op.
    - Cannot release more than reserved_total_usd.
    """
    trade_id = str(trade_id or "").strip()
    if not trade_id:
        raise ValueError("trade_id is required")
    now = now or _utc_now()

    existing = state.reservations.get(trade_id)
    if existing is None:
        raise ReleaseError(f"trade_id {trade_id} has no reservation to release")
    if existing.state == "released":
        # Idempotent success: no change.
        return state, existing
    if existing.state != "reserved":
        raise ReleaseError(f"trade_id {trade_id} is in invalid state {existing.state!r}")

    amount = existing.amount_usd
    if amount <= 0:
        raise ReleaseError(f"trade_id {trade_id} has invalid reserved amount {amount}")
    if state.reserved_total_usd < amount:
        # This should never happen if reserve/release are the only writers.
        raise ReleaseError(
            f"cannot release {amount} for trade_id {trade_id}: reserved_total_usd={state.reserved_total_usd}"
        )

    new_total = state.reserved_total_usd - amount
    released = TradeReservation(
        trade_id=existing.trade_id,
        amount_usd=existing.amount_usd,
        state="released",
        reserved_at=existing.reserved_at,
        released_at=now,
    )
    new_reservations = dict(state.reservations)
    new_reservations[trade_id] = released
    return CapitalReservationState(reserved_total_usd=new_total, reservations=new_reservations), released


def _state_from_firestore(doc: Dict[str, Any] | None) -> CapitalReservationState:
    if not doc:
        return CapitalReservationState.empty()
    reserved_total_usd = _d(doc.get("reserved_total_usd"))
    return CapitalReservationState(reserved_total_usd=reserved_total_usd, reservations={})


def _capital_doc_ref(
    *,
    db: Any,
    tenant_id: str,
    uid: str,
    broker_account_id: str,
):
    # Keep this single-document aggregate stable; per-trade docs are in a subcollection.
    # Path:
    #   tenants/{tenant_id}/capital_accounts/{uid}__{broker_account_id}
    doc_id = f"{uid}__{broker_account_id}"
    return db.collection("tenants").document(tenant_id).collection("capital_accounts").document(doc_id)


def reserve_capital_atomic(
    *,
    tenant_id: str,
    uid: str,
    broker_account_id: str,
    trade_id: str,
    amount_usd: float,
    buying_power_usd: Optional[float] = None,
    db: Any | None = None,
) -> Dict[str, Any]:
    """
    Atomically reserve capital in Firestore, idempotent by trade_id.

    Firestore schema:
    - Aggregate doc:
        tenants/{tenant_id}/capital_accounts/{uid}__{broker_account_id}
          - reserved_total_usd (string)
          - updated_at (timestamp)
    - Per-trade doc:
        .../reservations/{trade_id}
          - trade_id (string)
          - amount_usd (string)
          - state ("reserved"|"released")
          - reserved_at (timestamp)
          - released_at (timestamp|None)
    """
    tenant_id = str(tenant_id or "").strip()
    uid = str(uid or "").strip()
    broker_account_id = str(broker_account_id or "").strip()
    trade_id = str(trade_id or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not uid:
        raise ValueError("uid is required")
    if not broker_account_id:
        raise ValueError("broker_account_id is required")
    if not trade_id:
        raise ValueError("trade_id is required")

    amt = _d(amount_usd)
    bp = _d(buying_power_usd) if buying_power_usd is not None else None
    if amt <= 0:
        raise ValueError("amount_usd must be > 0")

    if admin_firestore is None:
        raise RuntimeError("firebase_admin is required for Firestore-backed capital reservation")

    # Lazy imports so pure helpers work without Firebase deps.
    from backend.persistence.firebase_client import get_firestore_client
    from backend.persistence.firestore_retry import with_firestore_retry

    client = db or get_firestore_client()
    cap_ref = _capital_doc_ref(db=client, tenant_id=tenant_id, uid=uid, broker_account_id=broker_account_id)
    res_ref = cap_ref.collection("reservations").document(trade_id)

    out: Dict[str, Any] = {}
    now = _utc_now()

    transaction = client.transaction()

    @admin_firestore.transactional  # type: ignore[union-attr]
    def _txn_body(txn):  # type: ignore[no-untyped-def]
        cap_snap = cap_ref.get(transaction=txn)
        res_snap = res_ref.get(transaction=txn)
        state = _state_from_firestore(cap_snap.to_dict() if getattr(cap_snap, "exists", False) else None)

        if getattr(res_snap, "exists", False):
            existing = res_snap.to_dict() or {}
            existing_state = str(existing.get("state") or "").strip().lower()
            existing_amount = _d(existing.get("amount_usd"))
            if existing_state == "reserved":
                if existing_amount != amt:
                    raise DuplicateReservationError(
                        f"trade_id {trade_id} already reserved for {existing_amount}, cannot reserve {amt}"
                    )
                out.update(existing)
                return
            raise DuplicateReservationError(
                f"trade_id {trade_id} already exists in state {existing_state!r}; cannot reserve again"
            )

        # Reserve via pure transition helper for correctness checks.
        new_state, reservation = apply_reserve(state=state, trade_id=trade_id, amount_usd=amt, buying_power_usd=bp, now=now)

        txn.set(
            cap_ref,
            {
                "tenant_id": tenant_id,
                "uid": uid,
                "broker_account_id": broker_account_id,
                "reserved_total_usd": str(new_state.reserved_total_usd),
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        txn.create(
            res_ref,
            {
                "tenant_id": tenant_id,
                "uid": uid,
                "broker_account_id": broker_account_id,
                **reservation.to_dict(),
                "created_at": admin_firestore.SERVER_TIMESTAMP,
            },
        )
        out.update(reservation.to_dict())

    with_firestore_retry(lambda: _txn_body(transaction))
    return out


def release_capital_atomic(
    *,
    tenant_id: str,
    uid: str,
    broker_account_id: str,
    trade_id: str,
    db: Any | None = None,
) -> Dict[str, Any]:
    """
    Atomically release capital for trade_id in Firestore, idempotent by trade_id.
    """
    tenant_id = str(tenant_id or "").strip()
    uid = str(uid or "").strip()
    broker_account_id = str(broker_account_id or "").strip()
    trade_id = str(trade_id or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not uid:
        raise ValueError("uid is required")
    if not broker_account_id:
        raise ValueError("broker_account_id is required")
    if not trade_id:
        raise ValueError("trade_id is required")

    if admin_firestore is None:
        raise RuntimeError("firebase_admin is required for Firestore-backed capital reservation")

    # Lazy imports so pure helpers work without Firebase deps.
    from backend.persistence.firebase_client import get_firestore_client
    from backend.persistence.firestore_retry import with_firestore_retry

    client = db or get_firestore_client()
    cap_ref = _capital_doc_ref(db=client, tenant_id=tenant_id, uid=uid, broker_account_id=broker_account_id)
    res_ref = cap_ref.collection("reservations").document(trade_id)

    out: Dict[str, Any] = {}
    now = _utc_now()

    transaction = client.transaction()

    @admin_firestore.transactional  # type: ignore[union-attr]
    def _txn_body(txn):  # type: ignore[no-untyped-def]
        cap_snap = cap_ref.get(transaction=txn)
        res_snap = res_ref.get(transaction=txn)

        state = _state_from_firestore(cap_snap.to_dict() if getattr(cap_snap, "exists", False) else None)

        if not getattr(res_snap, "exists", False):
            raise ReleaseError(f"trade_id {trade_id} has no reservation doc to release")

        existing = res_snap.to_dict() or {}
        existing_state = str(existing.get("state") or "").strip().lower()
        if existing_state == "released":
            out.update(existing)
            return
        if existing_state != "reserved":
            raise ReleaseError(f"trade_id {trade_id} is in invalid state {existing_state!r}")

        existing_amount = _d(existing.get("amount_usd"))
        # Model the currently reserved trade in the pure state to reuse assertions.
        modeled = CapitalReservationState(
            reserved_total_usd=state.reserved_total_usd,
            reservations={
                trade_id: TradeReservation(
                    trade_id=trade_id,
                    amount_usd=existing_amount,
                    state="reserved",
                    reserved_at=existing.get("reserved_at") or now,
                    released_at=None,
                )
            },
        )
        new_state, released = apply_release(state=modeled, trade_id=trade_id, now=now)

        txn.set(
            cap_ref,
            {
                "reserved_total_usd": str(new_state.reserved_total_usd),
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        txn.set(
            res_ref,
            {
                "state": "released",
                "released_at": released.released_at,
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        out.update({**existing, "state": "released", "released_at": released.released_at})

    with_firestore_retry(lambda: _txn_body(transaction))
    return out

