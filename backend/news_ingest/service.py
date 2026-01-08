from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from .config import NewsIngestConfig
from .news_api import NewsApiClient
from .store import FileCursorStore, FileNewsEventStore

logger = logging.getLogger(__name__)


@dataclass
class NewsIngestStats:
    polls: int = 0
    events_ingested: int = 0
    last_poll_ts: float = 0.0
    last_cursor: str | None = None


class NewsIngestor:
    """
    Polling ingestion loop (OBSERVE-only).

    - Reads events from a News API client (stubbed ok)
    - Writes raw events to an append-only file store
    - Persists a cursor so polling can resume after restarts
    """

    def __init__(self, *, cfg: NewsIngestConfig, client: NewsApiClient) -> None:
        self.cfg = cfg
        self.client = client
        self.store = FileNewsEventStore(data_root=cfg.data_root)
        self.cursor_store = FileCursorStore(cursor_path=cfg.cursor_path)
        self.stats = NewsIngestStats()
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def poll_once(self) -> None:
        cursor = self.cursor_store.load()
        self.stats.last_cursor = cursor
        self.stats.last_poll_ts = time.time()
        self.stats.polls += 1

        res = self.client.fetch(cursor=cursor, limit=self.cfg.max_events_per_poll)
        batch = self.store.append_events(source=self.cfg.source, events=res.events)

        if res.next_cursor and res.next_cursor != cursor:
            self.cursor_store.save(res.next_cursor)
            self.stats.last_cursor = res.next_cursor

        self.stats.events_ingested += batch.count
        logger.info(
            "news_ingest.poll",
            extra={
                "polls": self.stats.polls,
                "events_ingested_total": self.stats.events_ingested,
                "batch_count": batch.count,
                "batch_path": batch.path,
                "cursor": self.stats.last_cursor,
                "source": self.cfg.source,
            },
        )

    def run_forever(self) -> None:
        logger.info(
            "news_ingest.start",
            extra={
                "poll_interval_s": self.cfg.poll_interval_s,
                "max_events_per_poll": self.cfg.max_events_per_poll,
                "data_root": str(self.cfg.data_root),
                "cursor_path": str(self.cfg.cursor_path),
                "source": self.cfg.source,
            },
        )

        hb_interval_s = float((os.environ.get("HEARTBEAT_LOG_INTERVAL_S") or "60").strip() or "60")
        hb_interval_s = max(5.0, hb_interval_s)
        last_hb = 0.0

        while not self._stop:
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception as e:
                # Fail-open for ingestion (keep running), but be loud.
                logger.exception("news_ingest.poll_failed: %s", e)

            now = time.monotonic()
            if (now - last_hb) >= hb_interval_s:
                last_hb = now
                logger.info(
                    "news_ingest.heartbeat",
                    extra={
                        "polls": self.stats.polls,
                        "events_ingested_total": self.stats.events_ingested,
                        "last_poll_age_s": max(0.0, time.time() - (self.stats.last_poll_ts or 0.0)),
                        "cursor": self.stats.last_cursor,
                        "source": self.cfg.source,
                    },
                )

            elapsed = max(0.0, time.monotonic() - started)
            sleep_s = max(0.0, float(self.cfg.poll_interval_s) - elapsed)
            # Sleep in small increments so SIGTERM can stop promptly.
            while (sleep_s > 0.0) and (not self._stop):
                step = min(1.0, sleep_s)
                time.sleep(step)
                sleep_s -= step

