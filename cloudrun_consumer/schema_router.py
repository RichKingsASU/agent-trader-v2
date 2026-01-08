from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set

from handlers import ingest_health, system_events


HandlerFn = Callable[[Dict[str, Any], "EventContext"], None]


@dataclass(frozen=True)
class EventContext:
    message_id: str
    topic: str
    schema_version: str
    published_at_iso: str
    event_type: str
    subscription: str
    attributes: Dict[str, str]


class SchemaRouter:
    """
    Routes incoming events to a handler based on topic / eventType / payload hints.
    """

    def __init__(self) -> None:
        self._supported_versions: Set[str] = set(
            v.strip() for v in os.getenv("SUPPORTED_SCHEMA_VERSIONS", "1").split(",") if v.strip()
        )
        self._subscription_topic_map: Dict[str, str] = {}
        raw_map = os.getenv("SUBSCRIPTION_TOPIC_MAP", "").strip()
        if raw_map:
            try:
                self._subscription_topic_map = json.loads(raw_map)
            except Exception:
                self._subscription_topic_map = {}
        self._default_topic = os.getenv("DEFAULT_TOPIC", "unknown")

    @property
    def supported_versions(self) -> Set[str]:
        return set(self._supported_versions)

    def resolve_topic(self, subscription: str, attributes: Dict[str, str], payload: Dict[str, Any]) -> str:
        for k in ("topic", "pubsubTopic", "sourceTopic"):
            v = attributes.get(k) or payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        if subscription and subscription in self._subscription_topic_map:
            return str(self._subscription_topic_map[subscription])
        return self._default_topic

    def resolve_event_type(self, attributes: Dict[str, str], payload: Dict[str, Any]) -> str:
        for k in ("eventType", "type", "kind"):
            v = attributes.get(k) or payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return "unknown"

    def handler_for(self, topic: str, event_type: str, payload: Dict[str, Any]) -> Optional[HandlerFn]:
        t = (topic or "").lower()
        et = (event_type or "").lower()

        # Explicit eventType routing (preferred)
        if et.startswith(("system.", "ops.", "service.")) or et in {"system_event", "service_status", "ops_service"}:
            return system_events.handle
        if et.startswith(("ingest.", "pipeline.")) or et in {"ingest_health", "pipeline_status", "ingest_pipeline"}:
            return ingest_health.handle

        # Topic-based routing
        if any(x in t for x in ("system", "ops", "service")):
            return system_events.handle
        if any(x in t for x in ("ingest", "pipeline", "health")):
            return ingest_health.handle

        # Payload-hint routing (fallback)
        if any(k in payload for k in ("service", "serviceName", "component", "app", "service_id")):
            return system_events.handle
        if any(k in payload for k in ("pipeline", "pipelineName", "ingestPipeline", "pipeline_id")):
            return ingest_health.handle

        return None
