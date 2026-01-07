from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class StalenessState(str, Enum):
    """
    Freshness classification for a signal at evaluation time.

    - FRESH: The signal is within policy limits; safe to use normally.
    - DEGRADED: The signal is old enough that strategies must down-weight it.
    - STALE: The signal is too old (or unknown freshness); strategies must refuse it
      or treat it as a hard constraint violation.
    """

    FRESH = "FRESH"
    DEGRADED = "DEGRADED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class SignalTimestamp:
    """
    Timestamp metadata required to reason about signal freshness.

    Contract notes:
    - All timestamps must be timezone-aware UTC datetimes.
    - `as_of_utc` is the effective time of the signal (event time / bar close time).
    - `published_utc` is when the signal was computed/emitted (optional).
    - `ingested_utc` is when the platform observed the signal (optional).
    """

    as_of_utc: datetime
    published_utc: datetime | None = None
    ingested_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """
    Policy thresholds used to map a signal's age into a `StalenessState`.

    Interpretation (recommended; enforcement lives outside this contract module):
    - age <= degraded_after: FRESH
    - degraded_after < age <= stale_after: DEGRADED
    - age > stale_after: STALE

    Governance:
    - No silent staleness: unknown/missing timestamps must not be treated as FRESH.
      Default is `missing_timestamp_state == STALE`.
    """

    degraded_after: timedelta
    stale_after: timedelta
    missing_timestamp_state: StalenessState = StalenessState.STALE


class SignalFreshness(ABC):
    """
    Read-only interface for evaluating signal freshness.

    This is a contracts-only boundary. Implementations may track timestamps from
    signal publishers, storage, or runtime observation, but strategies should
    depend only on this interface.
    """

    @abstractmethod
    def get_signal_state(self, signal_name: str) -> StalenessState:
        """
        Return the current `StalenessState` for the named signal.

        Implementations must not silently downgrade the meaning of STALE:
        if freshness cannot be determined, `missing_timestamp_state` semantics
        should apply (recommended default: STALE).
        """

