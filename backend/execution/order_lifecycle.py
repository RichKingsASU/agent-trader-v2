from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CanonicalOrderState(str, Enum):
    """
    Canonical (broker-agnostic) order lifecycle states.

    Notes:
    - PARTIALLY_FILLED is a non-terminal state between ACCEPTED and FILLED.
    - CANCELLED vs EXPIRED are terminal and disjoint.
    """

    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES: set[CanonicalOrderState] = {
    CanonicalOrderState.FILLED,
    CanonicalOrderState.CANCELLED,
    CanonicalOrderState.EXPIRED,
}


def canonicalize_broker_status(
    status: str | None, *, filled_qty: float | None = None
) -> Optional[CanonicalOrderState]:
    """
    Map broker-native status strings to canonical lifecycle states.

    This is intentionally tolerant across brokers (and across Alpaca's varying status vocabulary).
    """
    s = str(status or "").strip().lower()
    fq = float(filled_qty or 0.0)

    # If we have any fill quantity, treat unknown statuses as at least partially filled.
    if fq > 0 and s not in {"filled", "partially_filled"}:
        # Some brokers can report "accepted" with non-zero filled_qty in edge cases; preserve fill signal.
        return CanonicalOrderState.PARTIALLY_FILLED

    if s in {"new", "pending_new"}:
        return CanonicalOrderState.NEW
    if s in {"accepted"}:
        return CanonicalOrderState.ACCEPTED
    if s in {"replaced", "pending_replace", "pending_cancel"}:
        # Still an active, accepted order in the market.
        return CanonicalOrderState.ACCEPTED
    if s in {"partially_filled"}:
        return CanonicalOrderState.PARTIALLY_FILLED
    if s in {"filled"}:
        return CanonicalOrderState.FILLED
    if s in {"canceled", "cancelled"}:
        return CanonicalOrderState.CANCELLED
    if s in {"expired"}:
        return CanonicalOrderState.EXPIRED

    return None


def is_valid_transition(
    old: CanonicalOrderState | None, new: CanonicalOrderState | None
) -> bool:
    """
    Validate canonical lifecycle transitions.

    Primary expected path (as requested):
      NEW -> ACCEPTED -> FILLED | CANCELLED | EXPIRED

    We also tolerate broker realities:
    - NEW may skip directly to PARTIALLY_FILLED/FILLED (fast fills)
    - ACCEPTED may remain ACCEPTED across polls
    - PARTIALLY_FILLED may repeat across multiple partial fills
    - Terminal states are sticky (idempotent repeats allowed)
    """
    if new is None:
        # Unknown broker status: don't hard-fail the lifecycle validator.
        return True
    if old is None:
        return new in {
            CanonicalOrderState.NEW,
            CanonicalOrderState.ACCEPTED,
            CanonicalOrderState.PARTIALLY_FILLED,
            CanonicalOrderState.FILLED,
            CanonicalOrderState.CANCELLED,
            CanonicalOrderState.EXPIRED,
        }
    if old == new:
        return True
    if old in TERMINAL_STATES:
        # Terminal states cannot transition to non-terminal.
        return new in TERMINAL_STATES

    allowed: dict[CanonicalOrderState, set[CanonicalOrderState]] = {
        CanonicalOrderState.NEW: {
            CanonicalOrderState.ACCEPTED,
            CanonicalOrderState.PARTIALLY_FILLED,
            CanonicalOrderState.FILLED,
            CanonicalOrderState.CANCELLED,
            CanonicalOrderState.EXPIRED,
        },
        CanonicalOrderState.ACCEPTED: {
            CanonicalOrderState.PARTIALLY_FILLED,
            CanonicalOrderState.FILLED,
            CanonicalOrderState.CANCELLED,
            CanonicalOrderState.EXPIRED,
        },
        CanonicalOrderState.PARTIALLY_FILLED: {
            CanonicalOrderState.FILLED,
            CanonicalOrderState.CANCELLED,
            CanonicalOrderState.EXPIRED,
            CanonicalOrderState.PARTIALLY_FILLED,
        },
        # terminal handled above
        CanonicalOrderState.FILLED: set(),
        CanonicalOrderState.CANCELLED: set(),
        CanonicalOrderState.EXPIRED: set(),
    }
    return new in allowed.get(old, set())


def compute_delta_fill_qty(*, previous_cum_qty: float, new_cum_qty: float) -> float:
    """
    Compute safe delta fill qty from broker cumulative fills.
    """
    prev = float(previous_cum_qty or 0.0)
    cur = float(new_cum_qty or 0.0)
    if cur <= prev:
        return 0.0
    return cur - prev


@dataclass(frozen=True, slots=True)
class LifecycleUpdate:
    """
    Result of applying a broker status update.
    """

    canonical_state: CanonicalOrderState | None
    transition_valid: bool
    previous_cum_filled_qty: float
    new_cum_filled_qty: float
    delta_filled_qty: float

