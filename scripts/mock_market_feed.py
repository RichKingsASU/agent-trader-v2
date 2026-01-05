#!/usr/bin/env python3
"""
Mock market data publisher for local testing.

Publishes a fast "random walk" quote stream for AAPL to NATS:
  - URL: nats://localhost:4222
  - Subject: market.data.AAPL
  - Interval: 100ms

Payload schema:
  { "symbol": "AAPL", "price": 150.25, "bid": 150.20, "ask": 150.30, "timestamp": "<iso_string>" }
"""

from __future__ import annotations

import asyncio
import json
import random
import signal
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.common.nats.subjects import market_subject
from backend.common.schemas.codec import encode_message
from backend.common.schemas.models import MarketEventV1


try:
    from nats.aio.client import Client as NATS
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'nats-py'. Install it (e.g. `pip install nats-py`) "
        "or ensure your environment dependencies are installed.\n"
        f"Import error: {e}"
    )


@dataclass
class Config:
    nats_url: str = "nats://localhost:4222"
    tenant_id: str = os.getenv("TENANT_ID", "local")
    subject: str = ""  # optional override
    symbol: str = "AAPL"
    interval_s: float = 0.1  # 100ms
    start_price: float = 150.00


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round2(x: float) -> float:
    # Ensure JSON numbers remain numbers while staying human-friendly.
    return float(f"{x:.2f}")


async def run_forever(cfg: Config) -> None:
    nc = NATS()
    await nc.connect(servers=[cfg.nats_url], name="mock-market-feed")

    subject = cfg.subject.strip() if cfg.subject else market_subject(cfg.tenant_id, cfg.symbol)

    price = cfg.start_price
    spread = 0.10  # $0.10 total spread => bid/ask +/- $0.05

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # Fallback for platforms without add_signal_handler (rare in Linux).
            signal.signal(sig, lambda *_: _request_stop())

    try:
        while not stop_event.is_set():
            bid = price - (spread / 2.0)
            ask = price + (spread / 2.0)

            payload = {
                "symbol": cfg.symbol,
                "price": _round2(price),
                "bid": _round2(bid),
                "ask": _round2(ask),
                "timestamp": _iso_utc_now(),
            }

            evt = MarketEventV1(
                tenant_id=cfg.tenant_id,
                symbol=cfg.symbol,
                source="mock-market-feed",
                data=payload,
            )
            await nc.publish(subject, encode_message(evt))
            await asyncio.sleep(cfg.interval_s)

            # Random walk step: small, frequent increments (applied after publish
            # so the stream starts exactly at cfg.start_price).
            price += random.gauss(0.0, 0.05)
            price = max(0.01, price)
    finally:
        try:
            await nc.flush(timeout=1)
        finally:
            await nc.close()


def main() -> None:
    cfg = Config()
    try:
        asyncio.run(run_forever(cfg))
    except KeyboardInterrupt:
        # Ctrl+C handled for environments without signal handlers.
        pass


if __name__ == "__main__":
    main()

