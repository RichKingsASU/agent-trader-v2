"""
Canonical ingestion publisher module.

This is a thin compatibility shim so callers can import:
  - backend.ingestion.publisher

without needing to know the underlying messaging package layout.
"""

from __future__ import annotations

from backend.messaging.publisher import PubSubPublisher

__all__ = ["PubSubPublisher"]

