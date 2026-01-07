"""
Agent-to-agent messaging via an event bus abstraction.

This package provides:
- A small JSON envelope (`EventEnvelope`)
- Google Pub/Sub publisher/subscriber clients (lazy-imported)
- A minimal in-memory bus for local testing/examples
"""

from .envelope import EventEnvelope
from .publisher import PubSubPublisher
from .subscriber import PubSubSubscriber
from .local import InMemoryEventBus

__all__ = [
    "EventEnvelope",
    "PubSubPublisher",
    "PubSubSubscriber",
    "InMemoryEventBus",
]

