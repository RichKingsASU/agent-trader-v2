"""
Shared, versioned JSON message schemas for internal NATS messaging.

See: docs/MESSAGING.md
"""

from .codec import decode_message, encode_message  # noqa: F401
from .models import (  # noqa: F401
    FillEventV1,
    MarketEventV1,
    OpsEventV1,
    OrderRequestV1,
    SignalEventV1,
)

