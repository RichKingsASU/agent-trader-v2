from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream

from backend.ingestion.firebase_writer import FirebaseWriter, FirestorePaths
from backend.ingestion.rate_limit import Backoff, TokenBucket
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.observability.build_fingerprint import get_build_fingerprint


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).isoformat()


def log_json(event_type: str, **fields: Any) -> None:
    """
    Cloud Run-friendly structured logs: JSON lines to stdout.
    """
    # Convention:
    # - log_ts: when this log line was emitted
    # - ts: event timestamp (if applicable); otherwise equals log_ts
    log_ts = _ts()
    # "severity" is recognized by Google Cloud Logging.
    payload = {"event_type": event_type, "severity": fields.pop("severity", "INFO"), "log_ts": log_ts, **fields}
    payload.setdefault("ts", log_ts)
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)


@dataclass
class IngestConfig:
    tenant_id: str | None
    symbols: list[str]
    feed: DataFeed
    dry_run: bool
    tenant_id: str | None

    # Throttling / storm prevention
    per_symbol_min_interval_ms: int
    global_writes_per_sec: float
    global_burst: float
    flush_interval_ms: int

    # Heartbeat
    heartbeat_interval_s: float

    # Firestore schema
    firestore_project_id: str | None
    firestore_latest_collection: str

    # Runtime / reconnection
    stop_after_seconds: float | None
    backoff_base_s: float
    backoff_max_s: float


@dataclass
class QuoteSnapshot:
    symbol: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    alpaca_ts: datetime | None
    received_ts: datetime

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0


@dataclass
class IngestStats:
    quote_events: int = 0
    firestore_writes_ok: int = 0
    firestore_writes_err: int = 0
    heartbeat_writes_ok: int = 0
    heartbeat_writes_err: int = 0


class MarketDataIngestor:
    def __init__(self, cfg: IngestConfig, *, writer: FirebaseWriter | None = None) -> None:
        self.cfg = cfg
        self._stop = asyncio.Event()
        self._stats = IngestStats()

        self._last_symbol: str | None = None

        self._latest_by_symbol: Dict[str, QuoteSnapshot] = {}
        self._dirty_symbols: set[str] = set()
        self._last_write_monotonic_by_symbol: Dict[str, float] = {}

        self._bucket = TokenBucket(rate_per_sec=cfg.global_writes_per_sec, capacity=cfg.global_burst)

        paths = FirestorePaths(tenant_id=cfg.tenant_id, latest_collection=cfg.firestore_latest_collection)
        self._writer = writer
        if self._writer is None and not cfg.dry_run:
            self._writer = FirebaseWriter(project_id=cfg.firestore_project_id, paths=paths)

        self._wss: StockDataStream | None = None
        self._backoff: Backoff | None = None
        self._reset_backoff_on_first_quote: bool = False

    @property
    def stats(self) -> IngestStats:
        return self._stats

    def request_stop(self) -> None:
        self._stop.set()
        # Best-effort: break out of an in-flight websocket run().
        try:
            if self._wss is not None:
                self._wss.stop()
        except Exception:
            pass

    async def _quote_handler(self, data: Any) -> None:
        """
        Alpaca StockDataStream quote callback.
        """
        self._stats.quote_events += 1

        # If we successfully receive data after a (re)connect, reset the reconnect backoff.
        if self._reset_backoff_on_first_quote and self._backoff is not None:
            self._backoff.reset()
            self._reset_backoff_on_first_quote = False
            log_json("reconnect_recovered", status="ok")

        symbol = getattr(data, "symbol", None) or ""
        if not isinstance(symbol, str) or not symbol.strip():
            log_json(
                "quote",
                status="ignored_missing_symbol",
                data_type=type(data).__name__,
                severity="WARNING",
            )
            return
        symbol = symbol.strip().upper()
        bid = getattr(data, "bid_price", None)
        ask = getattr(data, "ask_price", None)
        bid_size = getattr(data, "bid_size", None)
        ask_size = getattr(data, "ask_size", None)
        alpaca_ts = getattr(data, "timestamp", None)
        if isinstance(alpaca_ts, str):
            # best effort parse; keep as string in logs if parsing fails
            try:
                alpaca_ts = datetime.fromisoformat(alpaca_ts.replace("Z", "+00:00"))
            except Exception:
                alpaca_ts = None

        snap = QuoteSnapshot(
            symbol=symbol,
            bid=float(bid) if bid is not None else None,
            ask=float(ask) if ask is not None else None,
            bid_size=float(bid_size) if bid_size is not None else None,
            ask_size=float(ask_size) if ask_size is not None else None,
            alpaca_ts=alpaca_ts if isinstance(alpaca_ts, datetime) else None,
            received_ts=_utc_now(),
        )

        self._last_symbol = symbol or self._last_symbol
        self._latest_by_symbol[symbol] = snap
        self._dirty_symbols.add(symbol)

        log_json(
            "quote",
            symbol=symbol,
            bid=snap.bid,
            ask=snap.ask,
            price=snap.mid,
            ts=_ts(snap.alpaca_ts or snap.received_ts),
        )

    async def _flush_loop(self) -> None:
        """
        Coalesces quote updates and writes at a controlled pace.
        """
        per_symbol_min_s = max(0.0, self.cfg.per_symbol_min_interval_ms / 1000.0)
        flush_sleep = max(0.01, self.cfg.flush_interval_ms / 1000.0)

        while not self._stop.is_set():
            wrote_any = False
            pending: list[tuple[str, dict[str, Any]]] = []
            pending_monotonic: dict[str, float] = {}

            # Iterate a snapshot so we can modify dirty set while iterating.
            for symbol in list(self._dirty_symbols):
                if self._stop.is_set():
                    break

                snap = self._latest_by_symbol.get(symbol)
                if not snap:
                    self._dirty_symbols.discard(symbol)
                    continue

                last_w = self._last_write_monotonic_by_symbol.get(symbol, 0.0)
                now_m = time.monotonic()
                if per_symbol_min_s and (now_m - last_w) < per_symbol_min_s:
                    continue

                if not self._bucket.try_consume(1.0):
                    # Global limiter hit; back off until next iteration.
                    break

                payload: dict[str, Any] = {
                    "symbol": symbol,
                    # Canonical UI fields
                    "bid_price": snap.bid,
                    "ask_price": snap.ask,
                    # Back-compat / internal fields
                    "bid": snap.bid,
                    "ask": snap.ask,
                    "bid_size": snap.bid_size,
                    "ask_size": snap.ask_size,
                    "price": snap.mid,
                    "ts": _ts(snap.alpaca_ts or snap.received_ts),
                    "updated_at": _ts(snap.received_ts),
                    "source": "alpaca",
                }

                if self.cfg.dry_run:
                    self._stats.firestore_writes_ok += 1
                    self._last_write_monotonic_by_symbol[symbol] = now_m
                    self._dirty_symbols.discard(symbol)
                    wrote_any = True
                    log_json(
                        "firestore_write",
                        symbol=symbol,
                        bid=snap.bid,
                        ask=snap.ask,
                        price=snap.mid,
                        ts=payload["ts"],
                        status="dry_run",
                    )
                    continue

                # Batch where safe: quote docs are independent per symbol.
                pending.append((symbol, payload))
                pending_monotonic[symbol] = now_m

                # Keep batch sizes reasonable (Firestore limit: 500 ops per commit).
                if len(pending) >= 450:
                    break

            if pending and not self.cfg.dry_run:
                try:
                    assert self._writer is not None
                    self._writer.write_latest_quotes_batch(pending)
                    self._stats.firestore_writes_ok += len(pending)
                    wrote_any = True

                    for symbol, payload in pending:
                        now_m = pending_monotonic.get(symbol, time.monotonic())
                        self._last_write_monotonic_by_symbol[symbol] = now_m
                        self._dirty_symbols.discard(symbol)
                        snap = self._latest_by_symbol.get(symbol)
                        log_json(
                            "firestore_write",
                            symbol=symbol,
                            bid=getattr(snap, "bid", None),
                            ask=getattr(snap, "ask", None),
                            price=getattr(snap, "mid", None),
                            ts=payload.get("ts"),
                            status="ok",
                            mode="batch",
                        )
                except Exception as e:
                    # Keep symbols dirty; we'll retry later under rate limits.
                    # Count errors per attempted doc to make metrics meaningful.
                    self._stats.firestore_writes_err += len(pending)

                    # Also apply per-symbol throttling on failure to avoid hot-looping
                    # when Firestore is transiently unhealthy.
                    for sym, _payload in pending:
                        self._last_write_monotonic_by_symbol[sym] = pending_monotonic.get(sym, time.monotonic())

                    # Log a single batch-level error (avoid log storms).
                    sample_syms = [sym for sym, _ in pending[:10]]
                    log_json(
                        "firestore_write_batch",
                        status="error",
                        error=str(e),
                        symbols_sample=sample_syms,
                        symbols_count=len(pending),
                        severity="ERROR",
                    )

            if not wrote_any:
                await asyncio.sleep(flush_sleep)
            else:
                # Yield to event loop without adding extra latency.
                await asyncio.sleep(0)

    async def _heartbeat_loop(self) -> None:
        """
        Writes ops/market_ingest at least every heartbeat_interval_s.
        """
        interval = max(1.0, float(self.cfg.heartbeat_interval_s))

        while not self._stop.is_set():
            payload = {
                "ts": _ts(),
                "status": "running",
                "last_symbol": self._last_symbol,
            }

            if self.cfg.dry_run:
                self._stats.heartbeat_writes_ok += 1
                log_json("heartbeat", last_symbol=self._last_symbol, status="dry_run", ts=payload["ts"])
            else:
                try:
                    assert self._writer is not None
                    self._writer.write_ops_market_ingest(payload)
                    self._stats.heartbeat_writes_ok += 1
                    log_json("heartbeat", last_symbol=self._last_symbol, status="ok", ts=payload["ts"])
                except Exception as e:
                    self._stats.heartbeat_writes_err += 1
                    log_json(
                        "heartbeat",
                        last_symbol=self._last_symbol,
                        status="error",
                        ts=payload["ts"],
                        error=str(e),
                        severity="ERROR",
                    )

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _stop_after_loop(self) -> None:
        if self.cfg.stop_after_seconds is None:
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=float(self.cfg.stop_after_seconds))
        except asyncio.TimeoutError:
            log_json("stop_after", status="triggered", seconds=self.cfg.stop_after_seconds)
            self.request_stop()

    async def run(self) -> IngestStats:
        """
        Runs ingestion with reconnect logic until stopped.
        """
        alpaca = load_alpaca_env(require_keys=not self.cfg.dry_run)
        backoff = Backoff(base_seconds=self.cfg.backoff_base_s, max_seconds=self.cfg.backoff_max_s)
        self._backoff = backoff

        # DRY_RUN can simulate quotes even without Alpaca credentials.
        if self.cfg.dry_run and (not alpaca.key_id or not alpaca.secret_key):
            log_json(
                "alpaca_connect",
                status="dry_run_no_creds",
                symbols=self.cfg.symbols,
                feed=str(self.cfg.feed),
            )

            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._heartbeat_loop())
                tg.create_task(self._flush_loop())
                tg.create_task(self._stop_after_loop())
                tg.create_task(self._simulate_quotes_loop())

            return self._stats

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._flush_loop())
            tg.create_task(self._stop_after_loop())

            while not self._stop.is_set():
                wss = None
                try:
                    wss = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=self.cfg.feed)
                    self._wss = wss
                    self._reset_backoff_on_first_quote = True
                    wss.subscribe_quotes(self._quote_handler, *self.cfg.symbols)
                    log_json("alpaca_connect", status="starting", symbols=self.cfg.symbols, feed=str(self.cfg.feed))
                    await wss.run()
                    # If the stream ends without raising, treat it as a disconnect and re-connect
                    # with the same backoff policy to prevent tight restart loops.
                    if not self._stop.is_set():
                        sleep_s = backoff.next_sleep()
                        log_json(
                            "alpaca_disconnect",
                            status="ended",
                            sleep_s=sleep_s,
                            attempt=backoff.attempt,
                            severity="WARNING",
                        )
                        try:
                            await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                        except asyncio.TimeoutError:
                            pass
                    else:
                        log_json("alpaca_disconnect", status="clean")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    sleep_s = backoff.next_sleep()
                    log_json(
                        "alpaca_disconnect",
                        status="error",
                        error=str(e),
                        sleep_s=sleep_s,
                        attempt=backoff.attempt,
                        severity="ERROR",
                    )
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                    except asyncio.TimeoutError:
                        pass
                finally:
                    try:
                        if wss is not None:
                            wss.stop()
                    except Exception:
                        pass
                    finally:
                        if self._wss is wss:
                            self._wss = None

        return self._stats

    async def _simulate_quotes_loop(self) -> None:
        """
        Generates synthetic quotes for DRY_RUN when Alpaca creds are missing.
        """

        class _SimQuote:
            def __init__(self, symbol: str, bid: float, ask: float, bid_size: float, ask_size: float, ts: datetime):
                self.symbol = symbol
                self.bid_price = bid
                self.ask_price = ask
                self.bid_size = bid_size
                self.ask_size = ask_size
                self.timestamp = ts

        px = 100.0
        while not self._stop.is_set():
            now = _utc_now()
            for sym in self.cfg.symbols:
                # Simple deterministic walk (no randomness to keep logs stable).
                px = px + 0.01
                bid = round(px - 0.01, 2)
                ask = round(px + 0.01, 2)
                q = _SimQuote(sym, bid, ask, 100.0, 100.0, now)
                await self._quote_handler(q)
            await asyncio.sleep(0.5)


def load_config_from_env() -> IngestConfig:
    def _env_bool(name: str, *, default: bool = False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")

    tenant_id = os.getenv("TENANT_ID") or None
    if isinstance(tenant_id, str):
        tenant_id = tenant_id.strip() or None

    symbols_str = os.getenv("MONITORED_SYMBOLS") or os.getenv("ALPACA_SYMBOLS") or "SPY"
    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    feed_str = os.getenv("ALPACA_DATA_FEED", "iex").lower().strip()
    feed = DataFeed.IEX if feed_str == "iex" else DataFeed.SIP

    dry_run = _env_bool("DRY_RUN", default=False)

    per_symbol_min_interval_ms = int(os.getenv("PER_SYMBOL_MIN_INTERVAL_MS", "1000"))
    global_writes_per_sec = float(os.getenv("GLOBAL_WRITES_PER_SEC", "20"))
    global_burst = float(os.getenv("GLOBAL_BURST", "40"))
    flush_interval_ms = int(os.getenv("FLUSH_INTERVAL_MS", "200"))

    heartbeat_interval_s = float(os.getenv("HEARTBEAT_INTERVAL_S", "15"))

    firestore_project_id = os.getenv("FIRESTORE_PROJECT_ID") or None
    firestore_latest_collection = (
        os.getenv("FIRESTORE_LIVE_QUOTES_COLLECTION")
        or os.getenv("FIRESTORE_LATEST_COLLECTION")
        or "live_quotes"
    )

    stop_after_seconds_env = os.getenv("STOP_AFTER_SECONDS")
    if stop_after_seconds_env:
        stop_after_seconds = float(stop_after_seconds_env)
    else:
        stop_after_seconds = None

    backoff_base_s = float(os.getenv("RECONNECT_BACKOFF_BASE_S", "1"))
    backoff_max_s = float(os.getenv("RECONNECT_BACKOFF_MAX_S", "60"))

    return IngestConfig(
        tenant_id=tenant_id,
        symbols=symbols,
        feed=feed,
        dry_run=dry_run,
        per_symbol_min_interval_ms=per_symbol_min_interval_ms,
        global_writes_per_sec=global_writes_per_sec,
        global_burst=global_burst,
        flush_interval_ms=flush_interval_ms,
        heartbeat_interval_s=heartbeat_interval_s,
        firestore_project_id=firestore_project_id,
        firestore_latest_collection=firestore_latest_collection,
        stop_after_seconds=stop_after_seconds,
        backoff_base_s=backoff_base_s,
        backoff_max_s=backoff_max_s,
    )


async def _amain() -> int:
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="market-data-ingest",
        intent="Continuously ingest stock quotes from Alpaca and write latest snapshots to Firestore.",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass
    cfg = load_config_from_env()
    ingestor = MarketDataIngestor(cfg)

    loop = asyncio.get_running_loop()
    shutdown_logged = False

    def _handle_signal(signum: int, _frame: Any | None = None) -> None:
        nonlocal shutdown_logged
        if not shutdown_logged:
            shutdown_logged = True
            try:
                print("SHUTDOWN_INITIATED: market-data-ingest", flush=True)
            except Exception:
                pass
        log_json("signal", status="received", signum=signum)
        ingestor.request_stop()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _handle_signal, int(s), None)
        except NotImplementedError:
            signal.signal(s, _handle_signal)

    log_json(
        "startup",
        status="ok",
        tenant_id=cfg.tenant_id,
        symbols=cfg.symbols,
        feed=str(cfg.feed),
        dry_run=cfg.dry_run,
        per_symbol_min_interval_ms=cfg.per_symbol_min_interval_ms,
        global_writes_per_sec=cfg.global_writes_per_sec,
        global_burst=cfg.global_burst,
        heartbeat_interval_s=cfg.heartbeat_interval_s,
        firestore_latest_collection=cfg.firestore_latest_collection,
    )

    try:
        stats = await ingestor.run()
        log_json(
            "shutdown",
            status="ok",
            quote_events=stats.quote_events,
            firestore_writes_ok=stats.firestore_writes_ok,
            firestore_writes_err=stats.firestore_writes_err,
            heartbeat_writes_ok=stats.heartbeat_writes_ok,
            heartbeat_writes_err=stats.heartbeat_writes_err,
        )
        return 0
    except Exception as e:
        log_json("shutdown", status="error", error=str(e), severity="ERROR")
        return 2


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
