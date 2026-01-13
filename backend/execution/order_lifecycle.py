from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
import threading


class OrderLifecycleState(str, Enum):
    """
    Canonical lifecycle states for broker orders.

    Notes:
    - We keep these vendor-neutral; brokers may have additional transient statuses
      (e.g., pending_cancel). Those are mapped into the closest canonical state.
    - PARTIALLY_FILLED is explicitly represented so we can validate partial-fill
      progress toward terminal FILLED.
    """

    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES: set[OrderLifecycleState] = {
    OrderLifecycleState.FILLED,
    OrderLifecycleState.CANCELLED,
    OrderLifecycleState.EXPIRED,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonicalize_broker_status(status: Any) -> str:
    return str(status or "").strip().lower()


def broker_order_to_state(
    *,
    broker_status: Any,
    filled_qty: Any = None,
    order_qty: Any = None,
) -> OrderLifecycleState | None:
    """
    Map broker payload status/fill fields to a canonical lifecycle state.

    Returns None when the broker status is empty/unknown AND no fill inference is possible.
    """
    s = canonicalize_broker_status(broker_status)

    # Fill inference (best-effort; broker payloads vary).
    try:
        fq = float(filled_qty) if filled_qty is not None else 0.0
    except Exception:
        fq = 0.0
    oq = None
    try:
        oq = float(order_qty) if order_qty is not None else None
    except Exception:
        oq = None

    # Explicit terminal statuses first.
    if s in {"filled"}:
        return OrderLifecycleState.FILLED
    if s in {"canceled", "cancelled"}:
        return OrderLifecycleState.CANCELLED
    if s in {"expired"}:
        return OrderLifecycleState.EXPIRED

    # Explicit partial fill status.
    if s in {"partially_filled"}:
        return OrderLifecycleState.PARTIALLY_FILLED

    # If broker says "new/accepted/pending" but we already have fills, treat as partial/filled.
    if fq > 0:
        if oq is not None and oq > 0 and fq + 1e-9 >= oq:
            return OrderLifecycleState.FILLED
        return OrderLifecycleState.PARTIALLY_FILLED

    # Non-terminal active statuses.
    if s in {"new", "pending_new"}:
        return OrderLifecycleState.NEW
    if s in {"accepted", "replaced", "pending_replace", "pending_cancel"}:
        # "pending_cancel" remains active until the broker confirms "canceled".
        return OrderLifecycleState.ACCEPTED

    # Unknown/no status.
    if not s:
        return None
    # Best-effort fallback: treat unknown active statuses as ACCEPTED (keeps lifecycle moving).
    return OrderLifecycleState.ACCEPTED


ALLOWED_TRANSITIONS: set[tuple[OrderLifecycleState, OrderLifecycleState]] = {
    # Required path (spec): NEW -> ACCEPTED -> terminal
    (OrderLifecycleState.NEW, OrderLifecycleState.ACCEPTED),
    (OrderLifecycleState.ACCEPTED, OrderLifecycleState.FILLED),
    (OrderLifecycleState.ACCEPTED, OrderLifecycleState.CANCELLED),
    (OrderLifecycleState.ACCEPTED, OrderLifecycleState.EXPIRED),
    # Partial fill path (practical brokers)
    (OrderLifecycleState.NEW, OrderLifecycleState.PARTIALLY_FILLED),
    (OrderLifecycleState.PARTIALLY_FILLED, OrderLifecycleState.PARTIALLY_FILLED),
    (OrderLifecycleState.PARTIALLY_FILLED, OrderLifecycleState.FILLED),
    (OrderLifecycleState.PARTIALLY_FILLED, OrderLifecycleState.CANCELLED),
    (OrderLifecycleState.PARTIALLY_FILLED, OrderLifecycleState.EXPIRED),
    # Broker can sometimes go NEW -> terminal (IOC cancels, immediate fills, etc.)
    (OrderLifecycleState.NEW, OrderLifecycleState.FILLED),
    (OrderLifecycleState.NEW, OrderLifecycleState.CANCELLED),
    (OrderLifecycleState.NEW, OrderLifecycleState.EXPIRED),
    # Self transitions (idempotent/no-op updates)
    (OrderLifecycleState.NEW, OrderLifecycleState.NEW),
    (OrderLifecycleState.ACCEPTED, OrderLifecycleState.ACCEPTED),
    (OrderLifecycleState.FILLED, OrderLifecycleState.FILLED),
    (OrderLifecycleState.CANCELLED, OrderLifecycleState.CANCELLED),
    (OrderLifecycleState.EXPIRED, OrderLifecycleState.EXPIRED),
}


def validate_transition(
    *, prev: OrderLifecycleState, nxt: OrderLifecycleState
) -> bool:
    if (prev, nxt) in ALLOWED_TRANSITIONS:
        return True
    # Once terminal, only allow self.
    if prev in TERMINAL_STATES:
        return bool(prev == nxt)
    return False


@dataclass(frozen=True)
class OrderTransition:
    broker_order_id: str
    prev: OrderLifecycleState | None
    nxt: OrderLifecycleState
    at_utc: datetime
    meta: dict[str, Any] = field(default_factory=dict)


class OrderLifecycleError(RuntimeError):
    pass


class OrderLifecycleTracker:
    """
    In-memory order lifecycle tracker + transition validator.

    Purpose:
    - Provide deterministic validation that orders follow a complete lifecycle.
    - Record observed transitions for reporting/debugging.

    Persistence:
    - This is intentionally in-memory (no DB required). It enforces correctness
      within a process and provides observability. Downstream persistence can be
      added later without changing the transition rules.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state_by_order_id: dict[str, OrderLifecycleState] = {}
        self._transitions: list[OrderTransition] = []

    def get_state(self, *, broker_order_id: str) -> OrderLifecycleState | None:
        with self._lock:
            return self._state_by_order_id.get(str(broker_order_id))

    def transitions(self) -> list[OrderTransition]:
        with self._lock:
            return list(self._transitions)

    def _record(self, tr: OrderTransition) -> None:
        self._transitions.append(tr)
        self._state_by_order_id[tr.broker_order_id] = tr.nxt

    def start_new(self, *, broker_order_id: str, at_utc: datetime | None = None, meta: dict[str, Any] | None = None) -> None:
        oid = str(broker_order_id).strip()
        if not oid:
            return
        now = at_utc or _utc_now()
        with self._lock:
            if oid in self._state_by_order_id:
                return
            self._record(
                OrderTransition(
                    broker_order_id=oid,
                    prev=None,
                    nxt=OrderLifecycleState.NEW,
                    at_utc=now,
                    meta=dict(meta or {}),
                )
            )

    def apply(
        self,
        *,
        broker_order_id: str,
        nxt: OrderLifecycleState,
        at_utc: datetime | None = None,
        meta: dict[str, Any] | None = None,
        strict: bool = True,
    ) -> OrderTransition:
        oid = str(broker_order_id).strip()
        if not oid:
            raise OrderLifecycleError("missing_broker_order_id")
        now = at_utc or _utc_now()
        with self._lock:
            prev = self._state_by_order_id.get(oid)
            if prev is None:
                # Implicit start at NEW if the caller didn't record it.
                self._record(
                    OrderTransition(
                        broker_order_id=oid,
                        prev=None,
                        nxt=OrderLifecycleState.NEW,
                        at_utc=now,
                        meta={"implicit": True, **dict(meta or {})},
                    )
                )
                prev = OrderLifecycleState.NEW

            if not validate_transition(prev=prev, nxt=nxt):
                msg = f"invalid_transition:{prev.value}->{nxt.value}"
                if strict:
                    raise OrderLifecycleError(msg)
                # Best-effort: do not record invalid transitions when non-strict.
                return OrderTransition(
                    broker_order_id=oid,
                    prev=prev,
                    nxt=nxt,
                    at_utc=now,
                    meta={"invalid": True, **dict(meta or {})},
                )

            tr = OrderTransition(
                broker_order_id=oid,
                prev=prev,
                nxt=nxt,
                at_utc=now,
                meta=dict(meta or {}),
            )
            self._record(tr)
            return tr

    def apply_from_broker_order(
        self,
        *,
        broker_order_id: str,
        broker_status: Any,
        filled_qty: Any = None,
        order_qty: Any = None,
        at_utc: datetime | None = None,
        meta: dict[str, Any] | None = None,
        strict: bool = True,
    ) -> OrderTransition | None:
        nxt = broker_order_to_state(broker_status=broker_status, filled_qty=filled_qty, order_qty=order_qty)
        if nxt is None:
            return None
        return self.apply(
            broker_order_id=broker_order_id,
            nxt=nxt,
            at_utc=at_utc,
            meta={
                "broker_status": canonicalize_broker_status(broker_status),
                "filled_qty": filled_qty,
                "order_qty": order_qty,
                **dict(meta or {}),
            },
            strict=strict,
        )


def required_edges() -> set[tuple[OrderLifecycleState, OrderLifecycleState]]:
    """
    Minimal required edges per spec.
    """
    return {
        (OrderLifecycleState.NEW, OrderLifecycleState.ACCEPTED),
        (OrderLifecycleState.ACCEPTED, OrderLifecycleState.FILLED),
        (OrderLifecycleState.ACCEPTED, OrderLifecycleState.CANCELLED),
        (OrderLifecycleState.ACCEPTED, OrderLifecycleState.EXPIRED),
    }


def missing_required_edges(*, observed: Iterable[OrderTransition]) -> set[tuple[OrderLifecycleState, OrderLifecycleState]]:
    obs = {(t.prev, t.nxt) for t in observed if t.prev is not None}
    req = required_edges()
    # type-ignore: set contains tuples with non-None prev in obs
    missing: set[tuple[OrderLifecycleState, OrderLifecycleState]] = set()
    for a, b in req:
        if (a, b) not in obs:
            missing.add((a, b))
    return missing

