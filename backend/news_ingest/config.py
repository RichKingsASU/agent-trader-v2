from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NewsIngestConfig:
    """
    Configuration for the news ingestion poller.

    All settings are intentionally "safe by default":
    - no execution
    - no strategy coupling
    - OBSERVE-only enforced in entrypoint (see main.py)
    """

    poll_interval_s: float
    max_events_per_poll: int
    data_root: Path
    cursor_path: Path
    source: str

    # Stubbed API settings (interface is implemented; network client is a placeholder).
    api_base_url: str
    api_key: str | None


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def from_env() -> NewsIngestConfig:
    data_root = Path(_env("DATA_PLANE_ROOT", "data") or "data")
    cursor_path = Path(_env("NEWS_INGEST_CURSOR_PATH", str(data_root / "news" / "cursor.json")) or "")
    return NewsIngestConfig(
        poll_interval_s=float(_env("NEWS_INGEST_POLL_INTERVAL_S", "30") or "30"),
        max_events_per_poll=int(_env("NEWS_INGEST_MAX_EVENTS_PER_POLL", "200") or "200"),
        data_root=data_root,
        cursor_path=cursor_path,
        source=_env("NEWS_INGEST_SOURCE", "news-api-stub") or "news-api-stub",
        api_base_url=_env("NEWS_API_BASE_URL", "https://example.invalid") or "https://example.invalid",
        api_key=_env("NEWS_API_KEY", None),
    )

