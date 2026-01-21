from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Sequence

from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream

from backend.common.ingest_switch import get_effective_ingest_enabled_state
from backend.ingestion.firebase_writer import FirebaseWriter, FirestorePaths
from backend.ingestion.rate_limit import Backoff, TokenBucket
from backend.messaging.publisher import PubSubPublisher
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session
from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.ws_reconnect_policy import (
    UnrecoverableAuthError,
    classify_ws_failure,
    ensure_retry_allowed,
)
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.safety.process_safety import startup_banner


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).isoformat()


def log_json(event_type: str, **fields: Any) -> None:
    """
    Cloud Run-friendly structured logs: JSON lines to stdout.
    """
    from backend.observability.ops_json_logger import log as _ops_log  # noqa: WPS433

    # Convention:
    # - log_ts: when this log line was emitted
    # - ts: event timestamp (if applicable); otherwise equals log_ts
    log_ts = _ts()
    ts = fields.pop("ts", log_ts)
    severity = fields.pop("severity", "INFO")

    # Prefer explicit service override; fall back to common env vars; else default.
    service = str(fields.pop("service", "") or os.getenv("SERVICE_NAME") or os.getenv("K_SERVICE") or "market-data-ingest")

    payload = {"event_type": event_type, "log_ts": log_ts, "ts": ts, **fields}
    # Emit with required base fields (service/git_sha/image_tag/agent_mode/severity).
    _ops_log(service, event_type, severity=str(severity), **payload)


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
        self._ingest_enabled_last: bool | None = None
        self._ingest_enabled_source_last: str | None = None

        self._heartbeat_pubsub: PubSubPublisher | None = None

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

        # Optional: emit an ingest heartbeat *event* to Pub/Sub for cross-service visibility.
        # This is separate from the Firestore heartbeat doc (ops/market_ingest).
        topic_id = (os.getenv("INGEST_HEARTBEAT_TOPIC_ID") or "").strip()
        project_id = (
            (os.getenv("PUBSUB_PROJECT_ID") or "").strip()
            or (os.getenv("GCP_PROJECT") or "").strip()
            or (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
        )
        if topic_id and project_id:
            pipeline_id = (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest").strip() or "market-ingest"
            git_sha = (os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "").strip() or None
            try:
                self._heartbeat_pubsub = PubSubPublisher(
                    project_id=project_id,
                    topic_id=topic_id,
                    agent_name=pipeline_id,
                    git_sha=git_sha,
                    validate_credentials=False,
                    shutdown_event=self._stop,
                )
            except Exception as e:
                # Never fail startup due to optional telemetry.
                log_json("ingest_heartbeat_pubsub", status="disabled", reason="init_failed", error=str(e), severity="WARNING")

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

    def close(self) -> None:
        """
        Best-effort close of network clients (Firestore).
        """
        try:
            if self._writer is not None:
                self._writer.close()
        except Exception:
            pass
        try:
            if self._heartbeat_pubsub is not None:
                self._heartbeat_pubsub.close()
        except Exception:
            pass

    def _effective_ingest_enabled(self, *, context: str) -> bool:
        enabled, source = get_effective_ingest_enabled_state(default_enabled=True)
        if self._ingest_enabled_last is None or enabled != self._ingest_enabled_last:
            self._ingest_enabled_last = enabled
            self._ingest_enabled_source_last = source
            log_json(
                "ingest_enabled_transition",
                status="enabled" if enabled else "disabled",
                enabled=bool(enabled),
                source=str(source or ""),
                context=str(context),
                severity="INFO" if enabled else "WARNING",
            )
        return bool(enabled)

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
            if not self._effective_ingest_enabled(context="flush_loop"):
                # Pause writes while disabled; yield to event loop.
                await asyncio.sleep(flush_sleep)
                continue

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
            enabled = self._effective_ingest_enabled(context="heartbeat_loop")
            payload = {
                "ts": _ts(),
                "status": "running" if enabled else "disabled",
                "last_symbol": self._last_symbol,
                "ingest_enabled": bool(enabled),
                "ingest_enabled_source": str(self._ingest_enabled_source_last or ""),
            }

            if self.cfg.dry_run:
                self._stats.heartbeat_writes_ok += 1
                log_json(
                    "heartbeat",
                    last_symbol=self._last_symbol,
                    status="dry_run",
                    ingest_enabled=bool(enabled),
                    ingest_enabled_source=source,
                    ts=payload["ts"],
                )
            else:
                try:
                    assert self._writer is not None
                    self._writer.write_ops_market_ingest(payload)
                    self._stats.heartbeat_writes_ok += 1
                    log_json(
                        "heartbeat",
                        last_symbol=self._last_symbol,
                        status="ok" if enabled else "paused",
                        ingest_enabled=bool(enabled),
                        ingest_enabled_source=source,
                        ts=payload["ts"],
                    )
                except Exception as e:
                    self._stats.heartbeat_writes_err += 1
                    log_json(
                        "heartbeat",
                        last_symbol=self._last_symbol,
                        status="error",
                        ts=payload["ts"],
                        ingest_enabled=bool(enabled),
                        ingest_enabled_source=source,
                        error=str(e),
                        severity="ERROR",
                    )

            # Synthetic heartbeat *event* (Pub/Sub) every interval (best-effort).
            if self._heartbeat_pubsub is not None:
                try:
                    event_payload = {
                        "pipeline_id": (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest"),
                        "tenant_id": self.cfg.tenant_id,
                        "status": "running" if enabled else "disabled",
                        "ingest_enabled": bool(enabled),
                        "source": str(self._ingest_enabled_source_last or ""),
                        "ts": payload["ts"],
                    }
                    # Offload sync Pub/Sub publish to a worker thread to avoid blocking the event loop.
                    await asyncio.wait_for(
                        asyncio.to_thread(self._heartbeat_pubsub.publish_event, event_type="ingest.heartbeat", payload=event_payload),
                        timeout=float(os.getenv("INGEST_HEARTBEAT_PUBLISH_TIMEOUT_S") or "2"),
                    )
                    log_json("ingest_heartbeat_pubsub", status="ok", ts=payload["ts"])
                except Exception as e:
                    log_json("ingest_heartbeat_pubsub", status="error", error=str(e), ts=payload["ts"], severity="WARNING")

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
        # Startup gate: record initial ingest-enabled state.
        self._effective_ingest_enabled(context="startup")

        alpaca = load_alpaca_env(require_keys=not self.cfg.dry_run)
        backoff = Backoff(base_seconds=self.cfg.backoff_base_s, max_seconds=self.cfg.backoff_max_s)
        self._backoff = backoff
        max_attempts = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "5"))
        min_sleep_s = float(os.getenv("RECONNECT_MIN_SLEEP_S", "0.5"))
        ingest_poll_s = float(os.getenv("INGEST_ENABLED_POLL_S", "5"))

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
                if not self._effective_ingest_enabled(context="run_loop"):
                    # If ingestion is disabled, ensure we are not holding a websocket connection.
                    try:
                        if self._wss is not None:
                            self._wss.stop()
                    except Exception:
                        pass
                    # Avoid tight loops while disabled; remain responsive to stop.
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=min(5.0, float(self.cfg.heartbeat_interval_s)))
                    except asyncio.TimeoutError:
                        pass
                    continue

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
                        sleep_s = max(sleep_s, min_sleep_s)
                        log_json(
                            "alpaca_disconnect",
                            status="ended",
                            sleep_s=sleep_s,
                            attempt=backoff.attempt,
                            failure_category="transient",
                            severity="WARNING",
                        )
                        try:
                            ensure_retry_allowed(attempt=backoff.attempt, max_attempts=max_attempts)
                        except Exception:
                            log_json(
                                "alpaca_reconnect_giveup",
                                status="max_attempts_exceeded",
                                attempt=backoff.attempt,
                                max_attempts=max_attempts,
                                failure_category="transient",
                                severity="ERROR",
                            )
                            raise
                        log_json(
                            "reconnect_attempt",
                            status="scheduled",
                            sleep_s=sleep_s,
                            attempt=backoff.attempt,
                            reason="alpaca_disconnect",
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
                    failure = classify_ws_failure(e)
                    if failure.is_auth_failure():
                        log_json(
                            "alpaca_auth_failure",
                            status="unrecoverable",
                            error_type=type(e).__name__,
                            error=str(e),
                            failure_category=failure.category,
                            http_status=failure.http_status,
                            classification_reason=failure.reason,
                            severity="ERROR",
                        )
                        raise UnrecoverableAuthError(str(e)) from e
                    sleep_s = backoff.next_sleep()
                    sleep_s = max(sleep_s, min_sleep_s)
                    if failure.is_rate_limited():
                        log_json(
                            "alpaca_rate_limited",
                            status="retrying_with_backoff",
                            error_type=type(e).__name__,
                            error=str(e),
                            attempt=backoff.attempt,
                            failure_category=failure.category,
                            http_status=failure.http_status,
                            classification_reason=failure.reason,
                            severity="WARNING",
                        )
                    log_json(
                        "alpaca_disconnect",
                        status="error",
                        error=str(e),
                        sleep_s=sleep_s,
                        attempt=backoff.attempt,
                        failure_category=failure.category,
                        http_status=failure.http_status,
                        classification_reason=failure.reason,
                        severity="ERROR",
                    )
                    try:
                        ensure_retry_allowed(attempt=backoff.attempt, max_attempts=max_attempts)
                    except Exception:
                        log_json(
                            "alpaca_reconnect_giveup",
                            status="max_attempts_exceeded",
                            attempt=backoff.attempt,
                            max_attempts=max_attempts,
                            failure_category=failure.category,
                            http_status=failure.http_status,
                            classification_reason=failure.reason,
                            severity="ERROR",
                        )
                        raise
                    log_json(
                        "reconnect_attempt",
                        status="scheduled",
                        sleep_s=sleep_s,
                        attempt=backoff.attempt,
                        reason="alpaca_disconnect_error",
                        error=str(e),
                        severity="WARNING",
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


def fetch_alpaca_bars_1m(
    *,
    data_base: str,
    headers: dict[str, str],
    sym: str,
    start_iso: str,
    end_iso: str,
    feed: str,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """
    Fetch 1-minute bars for a single symbol from Alpaca's REST API.

    Thin wrapper around the existing Alpaca bars REST shape used elsewhere in the repo:
    - response JSON contains {"bars": [...]}
    - each bar uses keys: t,o,h,l,c,v
    """
    # Local imports keep the ingest daemon lightweight for normal quote streaming.
    import requests  # noqa: WPS433
    from tenacity import retry, stop_after_attempt, wait_exponential  # noqa: WPS433

    base = str(data_base or "").rstrip("/")
    sym_u = str(sym or "").strip().upper()
    if not sym_u:
        return []

    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
    def _do() -> list[dict[str, Any]]:
        r = requests.get(
            f"{base}/{sym_u}/bars",
            headers=headers,
            params={
                "timeframe": "1Min",
                "start": start_iso,
                "end": end_iso,
                "limit": int(limit),
                "feed": feed,
                "adjustment": "all",
            },
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json() or {}
        bars = payload.get("bars", [])
        return bars if isinstance(bars, list) else []

    return _do()


def upsert_market_data_1m_bars(conn: Any, sym: str, bars: Sequence[dict[str, Any]]) -> int:
    """
    Upsert Alpaca 1-minute bars into Postgres `public.market_data_1m`.
    """
    if not bars:
        return 0

    # Import only when we actually upsert (keeps module import safe for non-DB runs).
    from psycopg2.extras import execute_values  # type: ignore[import-not-found]  # noqa: WPS433

    sym_u = str(sym or "").strip().upper()
    if not sym_u:
        return 0

    rows: list[tuple[Any, ...]] = []
    for b in bars:
        try:
            ts = normalize_alpaca_timestamp(b["t"])
            session = get_market_session(ts)
            o, h, l, c, v = b.get("o"), b.get("h"), b.get("l"), b.get("c"), b.get("v")
            # `market_data_1m` columns are effectively required for downstream consumers; skip incomplete bars.
            if o is None or h is None or l is None or c is None or v is None:
                continue
            rows.append((sym_u, ts, o, h, l, c, int(v), session))
        except Exception:
            continue

    if not rows:
        return 0

    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO public.market_data_1m (symbol, ts, open, high, low, close, volume, session)
                VALUES %s
                ON CONFLICT (ts, symbol) DO UPDATE
                  SET open=EXCLUDED.open,
                      high=EXCLUDED.high,
                      low=EXCLUDED.low,
                      close=EXCLUDED.close,
                      volume=EXCLUDED.volume,
                      session=EXCLUDED.session;
                """,
                rows,
            )
        conn.commit()
        return len(rows)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def ingest_historical_bars(symbols: Sequence[str], feed: str, days: int, data_base: str) -> None:
    """
    Thin backfill orchestrator: Alpaca REST -> Postgres `public.market_data_1m`.

    Requirements:
    - DB writes only (no Pub/Sub)
    - No secrets at import time (all runtime-only)
    """
    import datetime as dt  # noqa: WPS433

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("Missing required env var: DATABASE_URL")

    # Runtime-only Alpaca env resolution (env vars only; no Secret Manager at import).
    alpaca = load_alpaca_env(require_keys=True)
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}

    # Normalize `data_base` host into the per-symbol bars base used by `fetch_alpaca_bars_1m`.
    base = f"{str(data_base or '').rstrip('/')}/v2/stocks"

    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=int(days))
    start_iso = start.isoformat(timespec="seconds").replace("+00:00", "Z")
    end_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    syms = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    if not syms:
        return

    # Local import keeps the quote ingest daemon import-safe even if DB deps are absent.
    import psycopg2  # type: ignore[import-not-found]  # noqa: WPS433

    with psycopg2.connect(db_url) as conn:
        for sym in syms:
            bars = fetch_alpaca_bars_1m(
                data_base=base,
                headers=headers,
                sym=sym,
                start_iso=start_iso,
                end_iso=end_iso,
                feed=feed,
            )
            upsert_market_data_1m_bars(conn, sym, bars)


async def _amain() -> int:
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="market-data-ingest",
        intent="Continuously ingest stock quotes from Alpaca and write latest snapshots to Firestore.",
    )
    startup_banner(
        service="market-data-ingest",
        intent="Continuously ingest stock quotes from Alpaca and write latest snapshots to Firestore.",
    )
    try:
        fp = get_build_fingerprint()
        log_json("build_fingerprint", intent_type="build_fingerprint", service="market-data-ingest", **fp)
    except Exception:
        pass
    cfg = load_config_from_env()
    # Environment validation (fail-fast for 24/7 daemons).
    if not cfg.dry_run:
        # Validates required Alpaca credentials are present.
        load_alpaca_env(require_keys=True)
    if not cfg.symbols:
        log_json("startup", status="error", error="MONITORED_SYMBOLS resolved to empty", severity="ERROR")
        return 2
    ingestor = MarketDataIngestor(cfg)

    loop = asyncio.get_running_loop()
    shutdown_logged = False

    def _handle_signal(signum: int, _frame: Any | None = None) -> None:
        nonlocal shutdown_logged
        if not shutdown_logged:
            shutdown_logged = True
            try:
                from backend.observability.ops_json_logger import OpsLogger  # noqa: WPS433

                OpsLogger("market-data-ingest").shutdown(phase="initiated")
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
    except UnrecoverableAuthError as e:
        log_json("shutdown", status="auth_failure", error=str(e), severity="ERROR")
        return 1
    except Exception as e:
        log_json("shutdown", status="error", error=str(e), severity="ERROR")
        return 2
    finally:
        # Ensure network clients are closed even on fatal errors.
        try:
            ingestor.request_stop()
        except Exception:
            pass
        try:
            ingestor.close()
        except Exception:
            pass


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
