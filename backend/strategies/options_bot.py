import asyncio
import os
import time
import logging
import signal
from datetime import datetime, timedelta, timezone
from typing import Any
from nats.aio.client import Client as NATS

from backend.common.nats.subjects import market_wildcard_subject, signals_subject
from backend.common.schemas.codec import decode_message, encode_message
from backend.common.schemas.models import MarketEventV1, SignalEventV1
from backend.common.freshness import check_freshness
from backend.risk_allocator.warm_cache import get_warm_cache_buying_power_usd
from backend.common.logging import init_structured_logging
from backend.common.kill_switch import get_kill_switch_state

init_structured_logging(service="options-bot")
logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _validate_event_ts(ts: datetime) -> tuple[bool, str]:
    """
    Fail-closed timestamp validation for inbound market events.

    - Reject stale events (age > STRATEGY_EVENT_MAX_AGE_SECONDS)
    - Reject future-dated events beyond STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS
    """
    now = datetime.now(timezone.utc)
    max_age_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_AGE_SECONDS", 30.0))
    max_future_skew_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS", 5.0))

    # Future skew: reject if too far ahead.
    future_skew_s = (ts.astimezone(timezone.utc) - now).total_seconds()
    if future_skew_s > max_future_skew_s:
        return False, "future_ts"

    freshness = check_freshness(latest_ts=ts, stale_after=timedelta(seconds=max_age_s), now=now, source="nats:MarketEventV1")
    if not freshness.ok:
        return False, "stale_ts" if freshness.reason_code == "STALE_DATA" else "missing_ts"
    return True, "ok"


async def main():
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    stop = asyncio.Event()

    # Best-effort SIGTERM/SIGINT handling (K8s/Cloud Run friendly).
    def _handle_signal(signum: int, _frame: Any = None) -> None:  # type: ignore[no-untyped-def]
        try:
            logger.warning("options_bot.signal_received signum=%s; initiating shutdown", int(signum))
        except Exception:
            pass
        try:
            stop.set()
        except Exception:
            pass

    if asyncio.get_running_loop() is not None:
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, _handle_signal, int(s), None)
            except NotImplementedError:
                # Fallback for platforms without add_signal_handler.
                try:
                    signal.signal(s, _handle_signal)
                except Exception:
                    pass

    tenant_id = (os.getenv("TENANT_ID") or "local").strip() or "local"
    strategy_id = (os.getenv("STRATEGY_ID") or "options_delta_momentum").strip() or "options_delta_momentum"
    delta_threshold = float(os.getenv("DELTA_THRESHOLD", "0.55"))
    snapshot_refresh_s = float(os.getenv("ALPACA_SNAPSHOT_REFRESH_S", "5"))

    cached_buying_power: float = 0.0
    cached_at_mono: float = 0.0

    async def _get_buying_power_cached() -> float:
        nonlocal cached_buying_power, cached_at_mono
        now = time.monotonic()
        if cached_at_mono and (now - cached_at_mono) < snapshot_refresh_s:
            return cached_buying_power

        # Firestore client is synchronous; offload to a thread so we don't block the event loop.
        buying_power, _ = await asyncio.to_thread(get_warm_cache_available_capital_usd)
        cached_buying_power = float(buying_power or 0.0)
        cached_at_mono = now
        return cached_buying_power

    async def options_handler(msg):
        # Global kill switch: stop emitting new signals if execution is halted.
        kill, source = get_kill_switch_state()
        if kill:
            try:
                logger.warning("options_bot.kill_switch_active enabled=true source=%s; dropping market event", source)
            except Exception:
                pass
            return
        # Validate incoming market messages.
        evt = decode_message(MarketEventV1, msg.data)
        ok_ts, reason = _validate_event_ts(evt.ts)
        if not ok_ts:
            try:
                logger.warning(
                    "options_bot.drop_event timestamp_validation_failed reason=%s ts=%s symbol=%s",
                    reason,
                    getattr(evt, "ts", None),
                    getattr(evt, "symbol", None),
                )
            except Exception:
                pass
            return
        data = evt.data or {}

        root = str(data.get("root") or evt.symbol).strip()
        greeks = data.get("greeks") or {}
        
        # QUANT STRATEGY: "Delta Momentum"
        # Only buy if Delta > 0.55 (Strong momentum) 
        try:
            delta = float(greeks.get("delta"))
        except Exception:
            delta = None

        if delta is not None and delta > delta_threshold:
            logger.warning(
                "High delta detected; emitting buy_call signal",
                extra={"event_type": "options_bot.signal_detected", "root": root, "delta": delta},
            )
            
            # Warm-cache affordability gate: never emit a signal that the account cannot afford.
            # Options contracts typically represent 100 shares.
            try:
                price = float(data.get("price")) if data.get("price") is not None else None
            except Exception:
                price = None
            qty = 1
            est_notional = (price * 100.0 * qty) if price is not None else None
            buying_power = await _get_buying_power_cached()
            if est_notional is not None and buying_power > 0 and est_notional > buying_power:
                logger.warning(
                    "Skipping unaffordable signal",
                    extra={
                        "event_type": "options_bot.signal_skipped_unaffordable",
                        "root": root,
                        "est_notional": est_notional,
                        "buying_power": buying_power,
                    },
                )
                return

            signal_evt = SignalEventV1(
                tenant_id=evt.tenant_id,
                strategy_id=strategy_id,
                symbol=root,
                signal_type="buy_call",
                confidence=None,
                data={
                    "root_symbol": root,
                    "option_symbol": data.get("option_symbol"),
                    "option_type": data.get("type"),
                    "strike": data.get("strike"),
                    "expiry": data.get("expiry"),
                    "price": data.get("price"),
                    "quantity": 1,
                    "greeks": greeks,
                },
            )

            await nc.publish(
                signals_subject(evt.tenant_id, strategy_id, root),
                encode_message(signal_evt),
            )

    # Listen to options chains for SPY, IWM, QQQ
    subject = os.getenv("NATS_MARKET_SUBJECT") or market_wildcard_subject(tenant_id)
    await nc.subscribe(subject, cb=options_handler)
    logger.info(
        "Options bot active",
        extra={"event_type": "options_bot.subscribed", "subject": subject, "delta_threshold": delta_threshold},
    )

    loop_iter = 0
    while not stop.is_set():
        # Global kill switch: exit loop promptly (safe shutdown).
        kill, source = get_kill_switch_state()
        if kill:
            try:
                logger.warning("options_bot.kill_switch_active enabled=true source=%s; exiting", source)
            except Exception:
                pass
            break
        loop_iter += 1
        if loop_iter % 60 == 0:
            print(f"[options_bot] loop_iteration={loop_iter}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    # Graceful close (best-effort).
    try:
        await nc.drain()
    except Exception:
        try:
            await nc.close()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
