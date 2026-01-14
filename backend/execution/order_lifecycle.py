from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional


class OrderLifecycleState(str, Enum):
    """
    Canonical lifecycle states for an order.

    Contract (per issue):
      NEW → ACCEPTED → FILLED / CANCELLED / EXPIRED
    """

    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    def is_terminal(self) -> bool:
        return self in {OrderLifecycleState.FILLED, OrderLifecycleState.CANCELLED, OrderLifecycleState.EXPIRED}


def broker_status_to_lifecycle_state(status: str) -> Optional[OrderLifecycleState]:
    """
    Map broker-native order statuses to our canonical lifecycle.

    Notes:
    - Brokers sometimes emit intermediate states that still mean "accepted/in-market".
    - We deliberately coalesce partial fill into ACCEPTED; fill deltas are tracked separately.
    """
    s = (status or "").strip().lower()
    if not s:
        return None

    # "NEW" bucket
    if s in {"new", "pending_new"}:
        return OrderLifecycleState.NEW

    # "ACCEPTED" bucket (in-market / working)
    if s in {
        "accepted",
        "replaced",
        "pending_replace",
        "pending_cancel",
        "partially_filled",
    }:
        return OrderLifecycleState.ACCEPTED

    # Terminal buckets
    if s in {"filled"}:
        return OrderLifecycleState.FILLED
    if s in {"canceled", "cancelled", "rejected"}:
        # Broker "rejected" is effectively terminal and cannot be filled.
        return OrderLifecycleState.CANCELLED
    if s in {"expired"}:
        return OrderLifecycleState.EXPIRED

    return None


class OrderLifecycleTransitionError(RuntimeError):
    pass


_ALLOWED: dict[Optional[OrderLifecycleState], set[OrderLifecycleState]] = {
    None: {OrderLifecycleState.NEW},
    OrderLifecycleState.NEW: {OrderLifecycleState.ACCEPTED, OrderLifecycleState.FILLED, OrderLifecycleState.CANCELLED, OrderLifecycleState.EXPIRED},
    OrderLifecycleState.ACCEPTED: {OrderLifecycleState.FILLED, OrderLifecycleState.CANCELLED, OrderLifecycleState.EXPIRED},
    OrderLifecycleState.FILLED: set(),
    OrderLifecycleState.CANCELLED: set(),
    OrderLifecycleState.EXPIRED: set(),
}


@dataclass
class Transition:
    from_state: Optional[OrderLifecycleState]
    to_state: OrderLifecycleState
    synthetic: bool = False  # inserted to satisfy canonical lifecycle shape


def validate_transition(*, from_state: Optional[OrderLifecycleState], to_state: OrderLifecycleState) -> None:
    allowed = _ALLOWED.get(from_state, set())
    if to_state not in allowed:
        raise OrderLifecycleTransitionError(f"invalid_transition:{from_state}->{to_state}")


def advance_lifecycle(
    *,
    current: Optional[OrderLifecycleState],
    observed: OrderLifecycleState,
) -> List[Transition]:
    """
    Advance the lifecycle given an observed lifecycle state.

    Broker reality: some orders may jump NEW→FILLED (e.g., market orders that fill immediately).
    To preserve the canonical lifecycle contract, we optionally insert a synthetic ACCEPTED
    between NEW and terminal when needed.
    """
    if current == observed:
        return []

    # If we see a terminal from NEW, insert synthetic ACCEPTED first.
    if current == OrderLifecycleState.NEW and observed.is_terminal():
        validate_transition(from_state=current, to_state=OrderLifecycleState.ACCEPTED)
        validate_transition(from_state=OrderLifecycleState.ACCEPTED, to_state=observed)
        return [
            Transition(from_state=OrderLifecycleState.NEW, to_state=OrderLifecycleState.ACCEPTED, synthetic=True),
            Transition(from_state=OrderLifecycleState.ACCEPTED, to_state=observed, synthetic=False),
        ]

    validate_transition(from_state=current, to_state=observed)
    return [Transition(from_state=current, to_state=observed, synthetic=False)]


class InMemoryOrderLifecycle:
    """
    Minimal in-memory lifecycle tracker keyed by broker_order_id.

    This is used for strict validation and to compute "missing transitions" in logs/diagnostics.
    Persistence is intentionally out of scope here.
    """

    def __init__(self):
        self._state_by_order_id: dict[str, OrderLifecycleState] = {}

    def state(self, *, broker_order_id: str) -> Optional[OrderLifecycleState]:
        return self._state_by_order_id.get(str(broker_order_id))

    def observe(self, *, broker_order_id: str, broker_status: str) -> List[Transition]:
        oid = str(broker_order_id or "").strip()
        if not oid:
            raise ValueError("missing broker_order_id")
        st = broker_status_to_lifecycle_state(broker_status)
        if st is None:
            raise OrderLifecycleTransitionError(f"unknown_broker_status:{broker_status}")
        cur = self._state_by_order_id.get(oid)
        transitions = advance_lifecycle(current=cur, observed=st)
        if transitions:
            self._state_by_order_id[oid] = transitions[-1].to_state
        return transitions

    @staticmethod
    def missing_transitions(states: Iterable[OrderLifecycleState]) -> List[str]:
        """
        Report which canonical lifecycle steps are missing from an observed state sequence.
        """
        seen = set(states)
        missing: list[str] = []
        if OrderLifecycleState.NEW not in seen:
            missing.append("NEW")
        if OrderLifecycleState.ACCEPTED not in seen:
            missing.append("ACCEPTED")
        if not (OrderLifecycleState.FILLED in seen or OrderLifecycleState.CANCELLED in seen or OrderLifecycleState.EXPIRED in seen):
            missing.append("TERMINAL(FILLED|CANCELLED|EXPIRED)")
        return missing

