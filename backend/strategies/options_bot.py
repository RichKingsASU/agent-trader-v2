import asyncio
import os
import time
import logging
from nats.aio.client import Client as NATS

from backend.common.nats.subjects import market_wildcard_subject, signals_subject
from backend.common.schemas.codec import decode_message, encode_message
from backend.common.schemas.models import MarketEventV1, SignalEventV1
from backend.alpaca_signal_trader import get_warm_cache_buying_power_usd
from backend.common.logging import init_structured_logging

init_structured_logging(service="options-bot")
logger = logging.getLogger(__name__)

async def main():
    nc = NATS()
    await nc.connect("nats://localhost:4222")

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
        buying_power, _ = await asyncio.to_thread(get_warm_cache_buying_power_usd)
        cached_buying_power = float(buying_power or 0.0)
        cached_at_mono = now
        return cached_buying_power

    async def options_handler(msg):
        # Validate incoming market messages.
        evt = decode_message(MarketEventV1, msg.data)
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

    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
