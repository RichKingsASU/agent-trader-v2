from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
import random
import time
from typing import Any, Iterable, Optional

from google.api_core import exceptions as gexc

logger = logging.getLogger(__name__)

from backend.persistence.firebase_client import get_firestore_client


def _stable_id(*parts: Any) -> str:
    s = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FirestoreCollections:
    options_flow: str = "options_flow"
    news_events: str = "news_events"
    accounts: str = "broker_accounts"


class FirestoreWriter:
    """
    Firestore writer for Stream Bridge events.

    Auth:
    - Uses Application Default Credentials (Cloud Run / GCE / local gcloud).
    - Do NOT commit service account JSON files.
    """

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        collections: FirestoreCollections | None = None,
        dry_run: bool = False,
    ) -> None:
        self.project_id = project_id
        self.collections = collections or FirestoreCollections()
        self.dry_run = dry_run

        self._db = get_firestore_client(project_id=project_id)

    def _retry(self, fn, *, max_attempts: int = 6, base_delay_s: float = 0.2, max_delay_s: float = 5.0):
        transient = (
            gexc.Aborted,
            gexc.DeadlineExceeded,
            gexc.InternalServerError,
            gexc.ResourceExhausted,
            gexc.ServiceUnavailable,
            gexc.TooManyRequests,
        )
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as e:
                if (not isinstance(e, transient)) or attempt >= (max_attempts - 1):
                    raise
                sleep_s = min(max_delay_s, base_delay_s * (2**attempt))
                time.sleep(random.random() * sleep_s)
                attempt += 1

    @classmethod
    async def create_from_env(cls) -> "FirestoreWriter":
        project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
        dry_run = os.getenv("DRY_RUN", "").strip() == "1"
        return cls(project_id=project_id, dry_run=dry_run)

    async def insert_options_flow(self, events: list[dict]) -> None:
        if not events:
            return
        if self.dry_run:
            logger.info("stream_bridge: options_flow dry_run count=%s", len(events))
            return

        col = self._db.collection(self.collections.options_flow)
        batch = self._db.batch()
        for e in events:
            doc_id = _stable_id(e.get("source"), e.get("event_ts"), e.get("option_symbol"), e.get("side"), e.get("size"))
            batch.set(col.document(doc_id), e, merge=True)
        self._retry(batch.commit)

    async def insert_news_events(self, events: list[dict]) -> None:
        if not events:
            return
        if self.dry_run:
            logger.info("stream_bridge: news_events dry_run count=%s", len(events))
            return

        col = self._db.collection(self.collections.news_events)
        batch = self._db.batch()
        for e in events:
            doc_id = _stable_id(e.get("source"), e.get("event_ts"), e.get("headline"))
            batch.set(col.document(doc_id), e, merge=True)
        self._retry(batch.commit)

    async def write_account_update(self, *, account_meta: dict, positions: list[dict], balances: list[dict]) -> None:
        """
        Stores the latest account snapshot under:
          broker_accounts/{broker}_{external_account_id}
        """
        broker = account_meta.get("broker") or "unknown"
        external_id = account_meta.get("external_account_id") or "unknown"
        doc_id = _stable_id(broker, external_id)

        payload = {
            "broker": broker,
            "external_account_id": external_id,
            "account_meta": account_meta,
            "positions": positions,
            "balances": balances,
        }

        if self.dry_run:
            logger.info("stream_bridge: account_update dry_run id=%s", doc_id)
            return

        self._retry(lambda: self._db.collection(self.collections.accounts).document(doc_id).set(payload, merge=True))
