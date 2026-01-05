from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

from google.api_core import exceptions as gexc

T = TypeVar("T")

_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    gexc.Aborted,
    gexc.DeadlineExceeded,
    gexc.InternalServerError,
    gexc.ResourceExhausted,
    gexc.ServiceUnavailable,
    gexc.TooManyRequests,
)


def with_firestore_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 6,
    base_delay_s: float = 0.2,
    max_delay_s: float = 5.0,
) -> T:
    """
    Retry transient Firestore errors with exponential backoff + full jitter.

    Intended for Firestore write operations (set/create/update/batch.commit).
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            is_transient = isinstance(e, _TRANSIENT_EXCEPTIONS)
            if (not is_transient) or attempt >= (max_attempts - 1):
                raise

            sleep_s = min(max_delay_s, base_delay_s * (2**attempt))
            time.sleep(random.random() * sleep_s)
            attempt += 1

