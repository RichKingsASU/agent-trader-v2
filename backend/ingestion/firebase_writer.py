from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import random
from typing import Any

from backend.time.nyse_time import parse_ts, utc_now

@dataclass(frozen=True)
class FirestorePaths:
    """
    Firestore schema conventions for ingestion.

    Heartbeat doc (required by ops tooling):
    - tenants/{tenant_id}/ops/market_ingest   (tenant-scoped; required for UI + rules)
    - ops/market_ingest                       (legacy/global; backend-only)

    Latest quote docs:
    - tenants/{tenant_id}/<latest_collection>/<symbol>   (tenant-scoped; required for UI + rules)
    - <latest_collection>/<symbol>                       (legacy/global; backend-only)
    """

    # When set, all writes are tenant-scoped under tenants/{tenant_id}/...
    tenant_id: str | None = None
    ops_collection: str = "ops"
    ops_market_ingest_doc: str = "market_ingest"
    # Contract: live quote snapshots are stored at live_quotes/{symbol}
    latest_collection: str = "live_quotes"


class FirebaseWriter:
    """
    Firestore writer wrapper.

    This intentionally isolates Firestore dependency & schema decisions so ingestion
    can be tested with a fake writer.
    """

    def __init__(self, *, project_id: str | None = None, paths: FirestorePaths | None = None):
        # Centralized, ADC-only Firebase Admin SDK init.
        from backend.persistence.firebase_client import get_firestore_client

        self._client = get_firestore_client(project_id=project_id)
        self.paths = paths or FirestorePaths()

    def close(self) -> None:
        """
        Best-effort close for the underlying Firestore client.

        This helps ensure gRPC channels are closed promptly on SIGTERM/SIGINT
        for long-running ingestion processes.
        """
        client = getattr(self, "_client", None)
        if client is None:
            return
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    def _quote_doc(self, symbol: str):
        sym = (symbol or "").strip().upper()
        if not sym:
            raise ValueError("symbol is required")

        if self.paths.tenant_id:
            return (
                self._client.collection("tenants")
                .document(self.paths.tenant_id)
                .collection(self.paths.latest_collection)
                .document(sym)
            )

        # Legacy/global path (not readable by client SDKs under current rules).
        return self._client.collection(self.paths.latest_collection).document(sym)

    def _ops_market_ingest_doc(self):
        if self.paths.tenant_id:
            return (
                self._client.collection("tenants")
                .document(self.paths.tenant_id)
                .collection(self.paths.ops_collection)
                .document(self.paths.ops_market_ingest_doc)
            )

        # Legacy/global path (not readable by client SDKs under current rules).
        return self._client.collection(self.paths.ops_collection).document(self.paths.ops_market_ingest_doc)

    def _coerce_timestamp(self, value: Any) -> datetime:
        """
        Normalize timestamps to timezone-aware UTC datetimes so Firestore stores a Timestamp.
        """
        if value is None:
            return utc_now()
        try:
            return parse_ts(value)
        except Exception:
            return utc_now()

    def _retry(self, fn, *, max_attempts: int = 6, base_delay_s: float = 0.2, max_delay_s: float = 5.0):
        """
        Retry transient Firestore errors with exponential backoff + jitter.
        """
        # Local import keeps module lightweight for tooling.
        from google.api_core import exceptions as gexc

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
                # Full jitter: sleep uniformly in [0, sleep_s)
                import time

                time.sleep(random.random() * sleep_s)
                attempt += 1

    def _normalize_latest_quote(self, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Canonical latest quote schema:
        - symbol: str
        - price OR bid/ask: numbers (at least one of these representations must be present)
        - ts: Firestore Timestamp (timezone-aware datetime)
        - source: "alpaca"
        """
        sym = (symbol or "").strip().upper()
        if not sym:
            raise ValueError("symbol is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        # Enforce a single source identifier for quote docs.
        source = payload.get("source", "alpaca")
        if source != "alpaca":
            raise ValueError("quote payload requires source='alpaca'")

        bid = payload.get("bid")
        ask = payload.get("ask")
        price = payload.get("price")
        has_bid_ask = isinstance(bid, (int, float)) and isinstance(ask, (int, float))
        has_price = isinstance(price, (int, float))
        if not (has_bid_ask or has_price):
            raise ValueError("quote payload requires numeric 'price' or both numeric 'bid' and 'ask'")

        ts = self._coerce_timestamp(payload.get("ts"))

        normalized: dict[str, Any] = {"symbol": sym, "source": "alpaca", "ts": ts}
        # Keep both when present; consumers can choose what they prefer.
        if has_price:
            normalized["price"] = float(price)
        if has_bid_ask:
            normalized["bid"] = float(bid)
            normalized["ask"] = float(ask)
        return normalized

    def _normalize_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        normalized = dict(payload)
        normalized["ts"] = self._coerce_timestamp(normalized.get("ts"))
        return normalized

    def write_latest_quote(self, symbol: str, payload: dict[str, Any]) -> None:
        normalized = self._normalize_latest_quote(symbol, payload)
        doc = self._quote_doc(normalized["symbol"])
        self._retry(lambda: doc.set(normalized, merge=True))

    def write_latest_quotes_batch(self, quotes: list[tuple[str, dict[str, Any]]]) -> None:
        """
        Batch writes latest quotes. Safe when quote docs are independent.
        """
        if not quotes:
            return

        batch = self._client.batch()
        op_count = 0

        def commit() -> None:
            nonlocal batch, op_count
            if op_count == 0:
                return
            self._retry(batch.commit)
            batch = self._client.batch()
            op_count = 0

        for symbol, payload in quotes:
            normalized = self._normalize_latest_quote(symbol, payload)
            batch.set(self._quote_doc(normalized["symbol"]), normalized, merge=True)
            op_count += 1
            if op_count >= 500:
                commit()

        commit()

    def write_ops_market_ingest(self, payload: dict[str, Any]) -> None:
        normalized = self._normalize_heartbeat(payload)
        doc = self._ops_market_ingest_doc()
        self._retry(lambda: doc.set(normalized, merge=True))

