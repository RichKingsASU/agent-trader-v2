from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CalmState(str, Enum):
    """
    Operator-facing, discrete calm state.

    This is intentionally *not* a numeric score. Discrete states are easier to
    reason about, less anxiety-inducing, and less likely to oscillate due to
    noise in underlying metrics.
    """

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass(frozen=True, slots=True)
class OperatorActionHint:
    """
    A human-centric suggestion for what to do next.

    Guidelines:
    - Short, concrete, and runbook-friendly.
    - Prefer *actions* over raw metrics.
    - Keep hints stable (avoid flapping) and limited in number.
    """

    title: str
    action: str
    # Optional link or identifier for a runbook/SOP.
    runbook_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SystemHealth:
    """
    Calm, operator-facing health snapshot.

    Design intent:
    - Reduce anxiety: a small number of stable signals.
    - Avoid noisy metrics: callers should not stuff high-frequency counters here.
    - Be actionable: include clear hints, not dashboards full of numbers.
    """

    state: CalmState
    headline: str
    # Stable, low-cardinality reason codes (for audit + search), e.g. "marketdata_stale".
    reason_codes: tuple[str, ...] = ()
    # Optional operator suggestions, ordered by importance.
    action_hints: tuple[OperatorActionHint, ...] = ()
    # When the snapshot was generated (UTC recommended).
    as_of_utc: datetime | None = None


class OpsCalmProvider(ABC):
    """
    Contract for producing the calm operator state for the system/component.
    """

    @abstractmethod
    def get_calm_state(self) -> SystemHealth: ...

