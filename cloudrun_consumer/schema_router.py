from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from cloudrun_consumer.handlers.system_events import handle_system_event
from cloudrun_consumer.handlers.market_ticks import handle_market_tick
from cloudrun_consumer.handlers.market_bars_1m import handle_market_bar_1m
from cloudrun_consumer.handlers.trade_signals import handle_trade_signal
from cloudrun_consumer.handlers.ingest_pipelines import handle_ingest_pipeline


@dataclass(frozen=True)
class RoutedHandler:
    name: str
    handler: Callable[..., dict[str, Any]]


def route_payload(
    *,
    payload: dict[str, Any],
    attributes: dict[str, str],
    topic: Optional[str] = None,
) -> Optional[RoutedHandler]:
    """
    Phase 1 router: system events -> ops_services.

    This intentionally does NOT modify producers. We route based on shape:
    `service` + `timestamp` indicates a system event record.
    """
    _ = attributes  # reserved for future schemaVersion routing
    if isinstance(payload.get("service"), str) and payload.get("service"):
        if payload.get("timestamp") is not None:
            return RoutedHandler(name="system_events", handler=handle_system_event)

    # Topic-based routing for additional streams.
    t = (topic or "").strip()
    if t == "market-ticks":
        return RoutedHandler(name="market_ticks", handler=handle_market_tick)
    if t == "market-bars-1m":
        return RoutedHandler(name="market_bars_1m", handler=handle_market_bar_1m)
    if t == "trade-signals":
        return RoutedHandler(name="trade_signals", handler=handle_trade_signal)
    if t in {"ingest-heartbeat", "ingest-pipelines", "ingest-pipeline-health"}:
        return RoutedHandler(name="ingest_pipelines", handler=handle_ingest_pipeline)
    return None

