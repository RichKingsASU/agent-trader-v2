import os
import asyncio
import logging
import time
from datetime import datetime, timezone
import psycopg2
from alpaca.data.live.stock import StockDataStream
from alpaca.data.enums import DataFeed

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from backend.common.alpaca_env import configure_alpaca_env
from backend.common.secrets import get_database_url
from backend.streams.alpaca_env import load_alpaca_env
import os

LAST_MARKETDATA_SOURCE: str = "alpaca_quotes_streamer"
_BACKOFF: Backoff | None = None
_RESET_BACKOFF_ON_FIRST_QUOTE: bool = False
_RETRY_WINDOW_STARTED_M: float | None = None
DB_URL: str | None = None


def get_last_marketdata_ts() -> datetime | None:
    return LAST_MARKETDATA_TS_UTC


def _mark_marketdata_seen(ts: datetime | None = None) -> None:
    """
    Updates the in-process marketdata freshness marker.
    This is intentionally lightweight and best-effort.
    """
    global LAST_MARKETDATA_TS_UTC
    if ts is None:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    LAST_MARKETDATA_TS_UTC = ts.astimezone(timezone.utc)


_batch_last_log_ts = 0.0
_batch_count = 0
_batch_publish_count = 0


def _symbols_from_env() -> list[str]:
    raw = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for s in syms:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


async def quote_data_handler(data):
    """Handler for incoming quote data."""
    # Consider each quote/tick as a heartbeat signal for marketdata freshness.
    marketdata_ticks_total.inc(1.0)
    mark_activity("marketdata")
    try:
        messages_received_total.inc(1.0, labels={"component": "marketdata-mcp-server", "stream": "alpaca_quotes"})
    except Exception:
        pass
    # If we successfully receive data after a (re)connect, reset the reconnect backoff.
    global _RESET_BACKOFF_ON_FIRST_QUOTE, _BACKOFF, _RETRY_WINDOW_STARTED_M
    if _RESET_BACKOFF_ON_FIRST_QUOTE and _BACKOFF is not None:
        try:
            _BACKOFF.reset()
            _RETRY_WINDOW_STARTED_M = None
            log_event("reconnect_recovered", level="INFO", component="marketdata-mcp-server", source=LAST_MARKETDATA_SOURCE)
        except Exception:
            pass
        _RESET_BACKOFF_ON_FIRST_QUOTE = False
    try:
        _mark_marketdata_seen(getattr(data, "timestamp", None))
    except Exception:
        _mark_marketdata_seen()

    # Intent point: data batch received (rate-limited; avoid per-tick spam).
    global _batch_last_log_ts, _batch_count, _batch_publish_count
    _batch_count += 1
    now = asyncio.get_running_loop().time()
    if (now - _batch_last_log_ts) >= 10.0:
        _batch_last_log_ts = now
        ctx = intent_start(
            "data_batch_received",
            "Received quote updates from Alpaca stream.",
            payload={
                "received_count": _batch_count,
                "published_count": _batch_publish_count,
                "sample_symbol": getattr(data, "symbol", None),
            },
        )
        intent_end(ctx, "success")
        _batch_count = 0
        _batch_publish_count = 0
    
    emit_ctx = None
    try:
        session = get_market_session(datetime.now(timezone.utc))
        global DB_URL
        if not DB_URL:
            raise RuntimeError("DATABASE_URL not configured (Secret Manager)")
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                emit_ctx = intent_start(
                    "marketdata_emit",
                    "Persist live quote to downstream store.",
                    payload={"symbol": data.symbol, "destination": "postgres", "table": "public.live_quotes"},
                )
                cur.execute(
                    """
                    INSERT INTO public.live_quotes (
                        symbol, bid_price, bid_size, ask_price, ask_size, last_update_ts, session
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                        bid_price = EXCLUDED.bid_price,
                        bid_size = EXCLUDED.bid_size,
                        ask_price = EXCLUDED.ask_price,
                        ask_size = EXCLUDED.ask_size,
                        last_update_ts = NOW(),
                        session = EXCLUDED.session;
                    """,
                    (data.symbol, data.bid_price, data.bid_size, data.ask_price, data.ask_size, session)
                )
                intent_end(emit_ctx, "success")
                _batch_publish_count += 1
                try:
                    messages_published_total.inc(
                        1.0,
                        labels={"component": "marketdata-mcp-server", "stream": "alpaca_quotes"},
                    )
                except Exception:
                    pass
    except psycopg2.Error as e:
        errors_total.inc(labels={"component": "marketdata-mcp-server"})
        try:
            log_event(
                "publish_failed",
                level="ERROR",
                component="marketdata-mcp-server",
                source=LAST_MARKETDATA_SOURCE,
                stream="alpaca_quotes",
                destination="postgres",
                error=f"{type(e).__name__}: {e}",
                symbol=getattr(data, "symbol", None),
            )
        except Exception:
            pass
        if emit_ctx is None:
            emit_ctx = intent_start(
                "marketdata_emit",
                "Persist live quote to downstream store.",
                payload={"symbol": getattr(data, "symbol", None), "destination": "postgres", "table": "public.live_quotes"},
            )
        intent_end(emit_ctx, "failure", error=e)

async def main(ready_event: asyncio.Event | None = None) -> None:
    """Main function to start the quote streamer.

    `ready_event` is an optional synchronization primitive used by the parent
    service to mark readiness once subscriptions are configured.
    """
    # Fail-fast: configure secrets from Secret Manager (no shell exports).
    _ = configure_alpaca_env(required=True)
    global DB_URL
    DB_URL = get_database_url(required=True)

    alpaca = load_alpaca_env()
    symbols = _symbols_from_env()

    # Deterministic Alpaca auth smoke tests (startup gate).
    # Runs before any subscriptions are made.
    if os.getenv("SKIP_ALPACA_AUTH_SMOKE_TESTS", "").strip().lower() not in ("1", "true", "yes", "y"):
        from backend.streams.alpaca_auth_smoke import run_alpaca_auth_smoke_tests_async  # noqa: WPS433

        feed = (os.getenv("ALPACA_DATA_FEED") or "iex").strip().lower() or "iex"
        timeout_s = float(os.getenv("ALPACA_AUTH_SMOKE_TIMEOUT_S", "5"))
        logging.info("Running Alpaca auth smoke tests (feed=%s, timeout_s=%s)...", feed, timeout_s)
        await run_alpaca_auth_smoke_tests_async(feed=feed, timeout_s=timeout_s)

    logging.info(f"Subscribing to quotes for: {symbols}")
    if not symbols:
        raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")

    # Reconnect policy (exponential backoff with jitter).
    backoff_base_s = float(os.getenv("RECONNECT_BACKOFF_BASE_S") or "1")
    backoff_max_s = float(os.getenv("RECONNECT_BACKOFF_MAX_S") or "60")
    max_retry_window_s = float(os.getenv("RECONNECT_MAX_RETRY_WINDOW_S") or "900")
    max_attempts = int(os.getenv("RECONNECT_MAX_ATTEMPTS") or "5")
    min_sleep_s = float(os.getenv("RECONNECT_MIN_SLEEP_S") or "0.5")

    backoff = Backoff(base_seconds=backoff_base_s, max_seconds=backoff_max_s)
    global _BACKOFF, _RESET_BACKOFF_ON_FIRST_QUOTE
    _BACKOFF = backoff
    global _RETRY_WINDOW_STARTED_M

    loop_iter = 0
    while True:
        loop_iter += 1
        log_event(
            "alpaca_quotes_stream_loop_iteration",
            level="INFO",
            component="marketdata-mcp-server",
            source=LAST_MARKETDATA_SOURCE,
            iteration=int(loop_iter),
        )
        wss_client: StockDataStream | None = None
        try:
            wss_client = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=DataFeed.IEX)
            _RESET_BACKOFF_ON_FIRST_QUOTE = True
            wss_client.subscribe_quotes(quote_data_handler, *symbols)

            # Readiness: subscriptions configured and stream loop about to run (first connect only).
            if ready_event is not None and (not ready_event.is_set()):
                try:
                    ready_event.set()
                except Exception:
                    pass

            log_event(
                "subscription_connect_attempt",
                level="INFO",
                component="marketdata-mcp-server",
                source=LAST_MARKETDATA_SOURCE,
                symbols_count=len(symbols),
                backoff_attempt=backoff.attempt,
            )
            await wss_client.run()

alpaca = load_alpaca_env()
SYMBOLS = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]
FEED = get_secret("ALPACA_DATA_FEED", fail_if_missing=False) or "iex"
FEED = FEED.strip().lower() or "iex"

if not SYMBOLS:
    raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")