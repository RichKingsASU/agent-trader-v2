from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from .models import OperatorNote


class OperatorOverridesProvider(Protocol):
    """
    Boundary interface for fetching active operator overrides/annotations.

    Implementations live outside vNEXT I/O boundaries (db, firestore, file, etc.).
    """

    def get_active_overrides(self, *, now_utc: datetime | None = None) -> Sequence[OperatorNote]:
        """
        Return active operator notes that should be considered "in force" at `now_utc`.

        Implementations should filter out expired items (when `expires_at_utc` is set).
        """

