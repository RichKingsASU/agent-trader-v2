"""
Hello Strategy (example tenant upload).

Contract:
- implement: on_market_event(event: dict) -> list[dict] | dict | None
- input event is a JSON object matching backend.strategy_runner.protocol.MarketEvent
- output intents are JSON objects matching backend.strategy_runner.protocol.OrderIntent
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


def on_market_event(event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    # Example: BUY 1 share if last trade price >= threshold.
    symbol = event.get("symbol", "")
    payload = event.get("payload", {}) or {}
    price = payload.get("price")

    threshold = 100.0
    if isinstance(price, (int, float)) and float(price) >= threshold:
        return [
            {
                "intent_id": f"hello_{uuid.uuid4().hex[:12]}",
                "ts": event.get("ts"),
                "symbol": symbol,
                "side": "buy",
                "qty": 1,
                "order_type": "market",
                "client_tag": "hello_strategy",
                "metadata": {"reason": f"price >= {threshold}", "price": float(price)},
            }
        ]
    return []

