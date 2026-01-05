from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from google.api_core import exceptions as gexc

from backend.persistence.firebase_client import get_firestore_client


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_timestamp(value: Any) -> datetime:
    """
    Normalize timestamps to timezone-aware UTC datetimes so Firestore stores a Timestamp.
    """
    if value is None:
        return _utc_now()

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        # Heuristic: treat very large values as epoch millis.
        seconds = float(value) / 1000.0 if float(value) > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

    if isinstance(value, str):
        s = value.strip()
        # datetime.fromisoformat doesn't accept "Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Fallback: treat as epoch millis/seconds string
            try:
                return _coerce_timestamp(float(s))
            except Exception as e:
                raise ValueError(f"Invalid timestamp string: {value!r}") from e

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raise TypeError(f"Unsupported timestamp type: {type(value).__name__}")


_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    gexc.Aborted,
    gexc.DeadlineExceeded,
    gexc.InternalServerError,
    gexc.ResourceExhausted,
    gexc.ServiceUnavailable,
    gexc.TooManyRequests,
)


def _with_retry(fn, *, max_attempts: int = 6, base_delay_s: float = 0.2, max_delay_s: float = 5.0):
    """
    Retry transient Firestore errors with exponential backoff + jitter.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            is_transient = isinstance(e, _TRANSIENT_EXCEPTIONS)
            if (not is_transient) or attempt >= (max_attempts - 1):
                raise

            sleep_s = min(max_delay_s, base_delay_s * (2**attempt))
            # Full jitter: random between 0 and sleep_s
            time.sleep(random.random() * sleep_s)
            attempt += 1


def _normalize_live_quote(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required")

    if not isinstance(payload, dict):
        raise TypeError("quote payload must be a dict")

    # Canonical quote schema: always source="alpaca"
    source = payload.get("source", "alpaca")
    if source != "alpaca":
        raise ValueError("quote payload requires source='alpaca'")

    # Enforce required quote fields.
    bid = payload.get("bid")
    ask = payload.get("ask")
    price = payload.get("price")
    has_bid_ask = isinstance(bid, (int, float)) and isinstance(ask, (int, float))
    has_price = isinstance(price, (int, float))
    if not (has_bid_ask or has_price):
        raise ValueError("quote payload requires numeric 'price' or both numeric 'bid' and 'ask'")

    # Timestamp: always store Firestore Timestamp (datetime) under 'ts'.
    ts = _coerce_timestamp(payload.get("ts") or payload.get("updated_at") or payload.get("last_update_ts"))

    normalized: dict[str, Any] = {"symbol": sym, "source": "alpaca", "ts": ts}
    # Keep both when present; consumers can choose what they prefer.
    if has_price:
        normalized["price"] = float(price)
    if has_bid_ask:
        normalized["bid"] = float(bid)
        normalized["ask"] = float(ask)
    return normalized


def write_quote(symbol: str, quote_dict: dict[str, Any]) -> None:
    """
    Writes a single quote to the `live_quotes/<symbol>` document.
    Enforces schema and retries transient failures.
    """
    db = get_firestore_client()
    normalized = _normalize_live_quote(symbol, quote_dict)
    doc_ref = db.collection("live_quotes").document(normalized["symbol"])
    _with_retry(lambda: doc_ref.set(normalized, merge=True))


def write_quotes_batch(quotes: Iterable[tuple[str, dict[str, Any]]]) -> None:
    """
    Batch write quotes (up to 500 ops per batch commit).
    """
    db = get_firestore_client()
    batch = db.batch()
    op_count = 0

    def commit_batch() -> None:
        nonlocal batch, op_count
        if op_count == 0:
            return
        _with_retry(batch.commit)
        batch = db.batch()
        op_count = 0

    for symbol, quote_dict in quotes:
        normalized = _normalize_live_quote(symbol, quote_dict)
        doc_ref = db.collection("live_quotes").document(normalized["symbol"])
        batch.set(doc_ref, normalized, merge=True)
        op_count += 1
        if op_count >= 500:
            commit_batch()

    commit_batch()


def write_heartbeat(heartbeat_dict: dict[str, Any]) -> None:
    """
    Writes a heartbeat to the `ops/market_ingest` document.
    Stores `ts` as a Firestore Timestamp and retries transient failures.
    """
    if not isinstance(heartbeat_dict, dict):
        raise TypeError("heartbeat payload must be a dict")

    payload = dict(heartbeat_dict)
    payload["ts"] = _coerce_timestamp(payload.get("ts"))
    db = get_firestore_client()
    doc_ref = db.collection("ops").document("market_ingest")
    _with_retry(lambda: doc_ref.set(payload, merge=True))
