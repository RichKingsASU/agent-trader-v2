from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class FetchResult:
    events: list[Mapping[str, Any]]
    next_cursor: str | None


class NewsApiClient(Protocol):
    """
    Minimal interface for a polled News API.

    Implementations MUST be read-only (no side effects beyond HTTP reads).
    """

    def fetch(self, *, cursor: str | None, limit: int) -> FetchResult: ...


class StubNewsApiClient:
    """
    Placeholder client.

    - Returns no events.
    - Advances cursor to a monotonic value to exercise the cursor pipeline if desired.
    """

    def __init__(self, *, source: str = "news-api-stub") -> None:
        self.source = source

    def fetch(self, *, cursor: str | None, limit: int) -> FetchResult:
        _ = (cursor, limit)
        # Cursor advances to "now" (monotonic-ish) so the service can prove it's alive.
        return FetchResult(events=[], next_cursor=str(int(time.time())))

