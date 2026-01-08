from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from handlers.system_events import handle_system_event


@dataclass(frozen=True)
class RoutedHandler:
    name: str
    handler: Callable[..., dict[str, Any]]


def route_payload(
    *,
    payload: dict[str, Any],
    attributes: dict[str, str],
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
    return None

