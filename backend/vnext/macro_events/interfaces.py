"""
Macro & event calendar interfaces (contracts only).

This module defines *read-only* data contracts and provider interfaces for
macro-economic and market-structure events (e.g., CPI, FOMC, earnings, holidays).

Important constraints:
- This module is *contracts only* (no network calls, no data fetching logic).
- This module must never directly trigger trades.
- Consumers may use these contracts only as *risk modifiers* (e.g., tighten
  limits, reduce sizing, widen circuit-breakers), not as entry signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Mapping, Protocol, Sequence


class EventSeverity(IntEnum):
    """
    Severity of an event from a risk-management perspective.

    This is intentionally an `IntEnum` so consumers can apply threshold logic,
    e.g. `if event.severity >= EventSeverity.HIGH: ...`.
    """

    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40


@dataclass(frozen=True, slots=True)
class EventWindow:
    """
    A time window in which an event is considered "risk-relevant".

    Implementations may choose to include buffer time before/after the scheduled
    event timestamp. Consumers should treat `start`/`end` as the authoritative
    risk window (not necessarily the exact release time).

    Notes:
    - `start` and `end` should be timezone-aware datetimes (recommended: UTC).
    - `end` should be >= `start`.
    """

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class MacroEvent:
    """
    A single macro or market event.

    This is a *read-only* representation. It does not contain trading logic and
    must not be used as an entry/exit trigger.

    Attributes:
    - `event_id`: Stable identifier (provider-scoped) for deduplication.
    - `title`: Human-readable name (e.g., "US CPI YoY").
    - `scheduled_time`: The primary scheduled time for the event (often the
      release time). The `window` should be used to determine risk-relevance.
    - `window`: The risk-relevant time window for the event.
    - `severity`: Risk severity ranking.
    - `region`: Optional region/country code (e.g., "US", "EU").
    - `source`: Optional provider name (e.g., "tradingeconomics", "manual").
    - `metadata`: Provider-specific extra fields (kept for transparency only).
    """

    event_id: str
    title: str
    scheduled_time: datetime
    window: EventWindow
    severity: EventSeverity
    region: str | None = None
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MacroEventProvider(Protocol):
    """
    Provider interface for macro/event calendars.

    Implementations are responsible for retrieving calendar data and mapping it
    into `MacroEvent` objects. This interface is intentionally minimal to keep
    it easy to mock in tests and safe to integrate incrementally.
    """

    def get_active_events(self, now: datetime, lookahead_minutes: int) -> Sequence[MacroEvent]:
        """
        Return events whose risk windows intersect with `[now, now+lookahead]`.

        Definitions:
        - "Active" means the event's `window` overlaps the query interval.
        - `now` should be timezone-aware (recommended: UTC).
        - `lookahead_minutes` must be non-negative.

        This must be treated as *read-only context* by consumers:
        - It does not and must not trigger trades.
        - It is used only to modify risk controls (limits, sizing, gating).
        """

