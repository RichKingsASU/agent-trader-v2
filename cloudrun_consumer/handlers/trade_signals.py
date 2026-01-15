from __future__ import annotations

from datetime import datetime
import logging
import os
from typing import Any, Optional

from cloudrun_consumer.event_utils import choose_doc_id, ordering_ts, parse_ts
from cloudrun_consumer.firestore_writer import SourceInfo
from cloudrun_consumer.replay_support import ReplayContext


_logger = logging.getLogger("cloudrun_consumer")


def _log(event_type: str, *, severity: str = "INFO", **fields: Any) -> None:
    """
    Emit structured logs consistent with cloudrun_consumer/main.py.
    """
    try:
        from backend.common.logging import log_standard_event  # lazy import for test environments

        log_standard_event(_logger, str(event_type), severity=str(severity).upper(), **fields)
    except Exception:
        return


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return bool(default)
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    return bool(default)


def _assert_paper_alpaca_base_url(url: str) -> str:
    """
    Hard safety: never allow live Alpaca trading host from this handler.
    """
    raw = str(url or "").strip() or "https://paper-api.alpaca.markets"
    lowered = raw.lower()
    if "paper-api.alpaca.markets" not in lowered:
        raise RuntimeError(f"REFUSED: non-paper Alpaca base URL: {raw!r}")
    return raw[:-1] if raw.endswith("/") else raw


def choose_trade_signal_dedupe_key(*, payload: dict[str, Any], message_id: str) -> str:
    """
    Deterministic replay dedupe key for trade_signals.

    Rules (in priority order):
    - payload.signal_id (preferred)
    - payload.eventId
    - Pub/Sub messageId (fallback)
    """
    if isinstance(payload, dict):
        for k in ("signal_id", "signalId"):
            v = payload.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        v = payload.get("eventId")
        if v is not None and str(v).strip():
            return str(v).strip()
    return str(message_id or "").strip()


def _extract_trade_signal_fields(
    *,
    payload: dict[str, Any],
    message_id: str,
    pubsub_published_at: datetime,
    source_topic: str,
) -> tuple[str, Optional[str], datetime, Optional[datetime], Optional[datetime], Optional[str], Optional[str], Optional[str], SourceInfo]:
    doc_id = choose_doc_id(payload=payload, message_id=message_id)
    event_id = None
    if "eventId" in payload and payload.get("eventId") is not None:
        event_id = str(payload.get("eventId")).strip() or None
    event_time = ordering_ts(payload=payload, pubsub_published_at=pubsub_published_at)

    produced_at = parse_ts(payload.get("producedAt")) if "producedAt" in payload else None
    published_at = parse_ts(payload.get("publishedAt")) if "publishedAt" in payload else None

    symbol = payload.get("symbol") if isinstance(payload.get("symbol"), str) else None
    strategy = payload.get("strategy") if isinstance(payload.get("strategy"), str) else None
    action = payload.get("action") if isinstance(payload.get("action"), str) else None

    source = SourceInfo(topic=str(source_topic or ""), message_id=str(message_id), published_at=pubsub_published_at)
    return (doc_id, event_id, event_time, produced_at, published_at, symbol, strategy, action, source)


def submit_alpaca_option_order(
    *,
    option_symbol: str,
    qty: int,
    side: str,
    order_type: str,
    time_in_force: str,
    client_order_id: str,
) -> dict:
    """
    Submit a single Alpaca PAPER options order.

    NOTE: This is the execution boundary for broker side-effects (called only after
    idempotency + EXECUTION_* gates and only for applied trade signals).
    """
    # Lazy imports keep unit tests/imports tolerant in minimal environments.
    from alpaca.common.exceptions import APIError  # type: ignore
    from alpaca.trading.client import TradingClient  # type: ignore
    from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore
    from alpaca.trading.requests import MarketOrderRequest  # type: ignore

    option_symbol = str(option_symbol or "").strip().upper()
    if not option_symbol:
        raise ValueError("missing_option_symbol")

    if not isinstance(qty, int) or qty <= 0:
        raise ValueError("invalid_qty")

    side_norm = str(side or "").strip().lower()
    if side_norm not in {"buy", "sell"}:
        raise ValueError("invalid_side")

    tif_norm = str(time_in_force or "").strip().lower() or "day"
    if tif_norm not in {"day", "gtc", "ioc", "fok"}:
        raise ValueError("invalid_time_in_force")

    order_type_norm = str(order_type or "").strip().lower() or "market"
    if order_type_norm != "market":
        # Keep scope tight per mission: one paper options order submission path.
        raise ValueError("unsupported_order_type")

    client_order_id = str(client_order_id or "").strip()
    if not client_order_id:
        raise ValueError("missing_client_order_id")

    # Secrets resolve via get_secret() (Secret Manager with optional env fallback).
    from backend.common.secrets import get_secret  # lazy import for test environments

    api_key = get_secret("APCA_API_KEY_ID", fail_if_missing=True)
    secret_key = get_secret("APCA_API_SECRET_KEY", fail_if_missing=True)
    base_url = get_secret("APCA_API_BASE_URL", fail_if_missing=False) or "https://paper-api.alpaca.markets"
    base_url = _assert_paper_alpaca_base_url(base_url)

    trading_client = TradingClient(
        api_key=api_key,
        secret_key=secret_key,
        paper=True,
        raw_data=True,  # Return raw dict response for logging/persistence.
        url_override=base_url,
    )

    order_data = MarketOrderRequest(
        symbol=option_symbol,
        qty=int(qty),
        side=OrderSide.BUY if side_norm == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce(tif_norm),
        client_order_id=client_order_id,
    )

    _log(
        "trade_signals.alpaca_options.submit_attempt",
        severity="INFO",
        option_symbol=option_symbol,
        qty=int(qty),
        side=side_norm,
        order_type=order_type_norm,
        time_in_force=tif_norm,
        client_order_id=client_order_id,
        alpaca_base_url=base_url,
        alpaca_paper=True,
    )
    try:
        resp = trading_client.submit_order(order_data=order_data)
        if not isinstance(resp, dict):
            # Defensive: raw_data=True should return dict; normalize anyway.
            resp = {"raw": str(resp)}
        return resp
    except APIError as e:
        _log(
            "trade_signals.alpaca_options.submit_failed",
            severity="ERROR",
            option_symbol=option_symbol,
            qty=int(qty),
            side=side_norm,
            order_type=order_type_norm,
            time_in_force=tif_norm,
            client_order_id=client_order_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise
    except Exception as e:
        _log(
            "trade_signals.alpaca_options.submit_failed",
            severity="ERROR",
            option_symbol=option_symbol,
            qty=int(qty),
            side=side_norm,
            order_type=order_type_norm,
            time_in_force=tif_norm,
            client_order_id=client_order_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise


def handle_trade_signal(
    *,
    payload: dict[str, Any],
    env: str,
    default_region: str,
    source_topic: str,
    message_id: str,
    pubsub_published_at: datetime,
    firestore_writer: Any,
    replay: ReplayContext | None = None,
) -> dict[str, Any]:
    """
    Materialize trade signal events into `trade_signals/{eventId|messageId}`.
    """
    _ = env
    _ = default_region

    replay_dedupe_key = choose_trade_signal_dedupe_key(payload=payload, message_id=message_id)
    doc_id, event_id, event_time, produced_at, published_at, symbol, strategy, action, source = _extract_trade_signal_fields(
        payload=payload,
        message_id=message_id,
        pubsub_published_at=pubsub_published_at,
        source_topic=source_topic,
    )
    applied, reason = firestore_writer.upsert_trade_signal(
        doc_id=doc_id,
        event_id=event_id,
        replay_dedupe_key=replay_dedupe_key,
        event_time=event_time,
        produced_at=produced_at,
        published_at=published_at,
        symbol=symbol,
        strategy=strategy,
        action=action,
        data=payload,
        source=source,
        replay=replay,
    )

    result: dict[str, Any] = {
        "kind": "trade_signals",
        "docId": doc_id,
        "symbol": symbol,
        "applied": bool(applied),
        "reason": str(reason),
        "eventTime": event_time.isoformat(),
    }

    # If the signal did not apply (dedupe/LWW no-op), do not perform broker side-effects.
    if not applied:
        return result

    # Execution boundary note:
    # - At this point the trade signal has been persisted and idempotency has been satisfied.
    # - Any broker submission below is a one-way side-effect guarded by EXECUTION_* toggles.
    if not (_bool_env("EXECUTION_ENABLED", False) and _bool_env("EXECUTION_CONFIRM", False)):
        return result

    # Options trade signal detection + field extraction (assumed validated upstream).
    option_symbol = (
        payload.get("option_symbol")
        or payload.get("optionSymbol")
        or payload.get("option_contract_symbol")
        or payload.get("optionContractSymbol")
    )
    if not isinstance(option_symbol, str) or not option_symbol.strip():
        return result

    qty_raw = payload.get("qty")
    if qty_raw is None:
        qty_raw = payload.get("quantity")
    if qty_raw is None:
        qty_raw = payload.get("size")
    try:
        qty = int(qty_raw)
    except Exception:
        _log(
            "trade_signals.alpaca_options.missing_fields",
            severity="ERROR",
            option_symbol=str(option_symbol),
            missing_or_invalid="qty",
        )
        return result

    side = payload.get("side") if isinstance(payload.get("side"), str) else None
    if side is None:
        side = action
    order_type = payload.get("order_type") if isinstance(payload.get("order_type"), str) else None
    if order_type is None:
        order_type = payload.get("orderType") if isinstance(payload.get("orderType"), str) else None
    time_in_force = payload.get("time_in_force") if isinstance(payload.get("time_in_force"), str) else None
    if time_in_force is None:
        time_in_force = payload.get("timeInForce") if isinstance(payload.get("timeInForce"), str) else None

    # Deterministic client order id for traceability (keep within typical Alpaca limits).
    client_order_id = payload.get("client_order_id") if isinstance(payload.get("client_order_id"), str) else None
    if client_order_id is None:
        client_order_id = payload.get("clientOrderId") if isinstance(payload.get("clientOrderId"), str) else None
    if not client_order_id:
        client_order_id = f"trade-signal-{doc_id}"
    client_order_id = str(client_order_id).strip().replace(" ", "-")[:48]

    try:
        resp = submit_alpaca_option_order(
            option_symbol=str(option_symbol),
            qty=qty,
            side=str(side or ""),
            order_type=str(order_type or "market"),
            time_in_force=str(time_in_force or "day"),
            client_order_id=client_order_id,
        )
        order_id = None
        if isinstance(resp, dict):
            order_id = resp.get("id") or resp.get("order_id") or resp.get("orderId")

        _log(
            "trade_signals.alpaca_options.submit_succeeded",
            severity="INFO",
            option_symbol=str(option_symbol).strip().upper(),
            qty=int(qty),
            side=str(side or "").strip().lower(),
            order_id=str(order_id) if order_id is not None else None,
            client_order_id=client_order_id,
            alpaca_response=resp,
        )
        result["alpacaOrderId"] = str(order_id) if order_id is not None else None

        # Trivial persistence: merge order_id onto the existing trade_signals doc (no schema redesign).
        try:
            db = getattr(firestore_writer, "_db", None)
            col_fn = getattr(firestore_writer, "_col", None)
            if db is not None and callable(col_fn):
                ref = db.collection(col_fn("trade_signals")).document(str(doc_id))
                patch: dict[str, Any] = {
                    "alpacaOrderId": str(order_id) if order_id is not None else None,
                    "alpacaClientOrderId": str(client_order_id),
                }
                patch = {k: v for k, v in patch.items() if v is not None}
                ref.set(patch, merge=True)
        except Exception as e:
            _log(
                "trade_signals.alpaca_options.persist_order_id_failed",
                severity="ERROR",
                docId=str(doc_id),
                error_type=type(e).__name__,
                error=str(e),
            )

    except Exception:
        # submit_alpaca_option_order logs the failure details.
        return result

    return result

