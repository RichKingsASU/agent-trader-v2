"""
Deprecated legacy handler.

This module used to implement a bespoke ingest health materializer with its own
ad-hoc context types. The canonical implementation lives in
`cloudrun_consumer.handlers.ingest_pipelines` and is routed by topic via
`cloudrun_consumer.schema_router`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from cloudrun_consumer.handlers.ingest_pipelines import handle_ingest_pipeline


def handle_ingest_health(
    *,
    payload: dict[str, Any],
    env: str,
    default_region: str,
    source_topic: str,
    message_id: str,
    pubsub_published_at: datetime,
    firestore_writer: Any,
    replay: Optional[Any] = None,
) -> dict[str, Any]:
    _ = replay
    return handle_ingest_pipeline(
        payload=payload,
        env=env,
        default_region=default_region,
        source_topic=source_topic,
        message_id=message_id,
        pubsub_published_at=pubsub_published_at,
        firestore_writer=firestore_writer,
    )


# Back-compat alias if anything still imports `handle`.
handle = handle_ingest_health

