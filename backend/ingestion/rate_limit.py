from __future__ import annotations

import random
import time
from dataclasses import dataclass


class TokenBucket:
    """
    Simple token bucket rate limiter.

    - rate_per_sec: tokens added per second
    - capacity: max burst tokens
    """

    def __init__(self, *, rate_per_sec: float, capacity: float) -> None:
        self.rate_per_sec = float(rate_per_sec)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        if elapsed <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_sec)

    def try_consume(self, tokens: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False


@dataclass
class Backoff:
    """
    Exponential backoff with full jitter.
    """

    base_seconds: float = 1.0
    max_seconds: float = 60.0
    factor: float = 2.0

    _attempt: int = 0

    @property
    def attempt(self) -> int:
        return self._attempt

    def reset(self) -> None:
        self._attempt = 0

    def next_sleep(self) -> float:
        self._attempt += 1
        cap = min(self.max_seconds, self.base_seconds * (self.factor ** (self._attempt - 1)))
        # Full jitter: random(0, cap)
        return random.random() * cap

