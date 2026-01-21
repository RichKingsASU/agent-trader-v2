from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LatchSnapshot:
    """
    Read-only snapshot of a latch holder.

    Times are based on `time.monotonic()` and are process-local.
    """

    name: str
    holder: str
    purpose: str
    acquired_at_mono: float
    expires_at_mono: float
    token: int

    def remaining_s(self, *, now_mono: Optional[float] = None) -> float:
        now = time.monotonic() if now_mono is None else float(now_mono)
        return max(0.0, self.expires_at_mono - now)

    def as_dict(self, *, now_mono: Optional[float] = None) -> Dict[str, Any]:
        now = time.monotonic() if now_mono is None else float(now_mono)
        return {
            "name": self.name,
            "holder": self.holder,
            "purpose": self.purpose,
            "acquired_at_mono": self.acquired_at_mono,
            "expires_at_mono": self.expires_at_mono,
            "remaining_s": max(0.0, self.expires_at_mono - now),
            "token": self.token,
        }


class LatchHandle:
    """
    A small release handle for the in-memory latch.

    Safe to call `release()` multiple times; only the first successful call releases.
    """

    __slots__ = ("_latch", "_token", "_released")

    def __init__(self, latch: InMemoryTtlLatch, token: int) -> None:
        self._latch = latch
        self._token = int(token)
        self._released = False

    def release(self) -> bool:
        if self._released:
            return False
        self._released = True
        return self._latch.release(self._token)

    def __enter__(self) -> "LatchHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.release()


class InMemoryTtlLatch:
    """
    A non-blocking, process-local latch with TTL auto-release.

    - In-memory only (no distributed state)
    - Intended as a coordination guard, not a correctness primitive
    - TTL expiry is enforced lazily on calls to `try_acquire()` / `snapshot()`
    """

    def __init__(self, *, name: str) -> None:
        self._name = str(name)
        self._mu = threading.Lock()
        self._state: Optional[LatchSnapshot] = None
        self._token_seq = 0

    def _maybe_expire_locked(self, *, now_mono: float) -> None:
        if self._state is None:
            return
        if now_mono < self._state.expires_at_mono:
            return

        expired = self._state
        self._state = None
        logger.info(
            "Latch auto-released (expired) name=%s holder=%s purpose=%s token=%s",
            expired.name,
            expired.holder,
            expired.purpose,
            expired.token,
        )

    def snapshot(self) -> Optional[LatchSnapshot]:
        now = time.monotonic()
        with self._mu:
            self._maybe_expire_locked(now_mono=now)
            return self._state

    def try_acquire(self, *, requester: str, ttl_s: float, purpose: str = "") -> Optional[LatchHandle]:
        """
        Attempt to acquire the latch immediately.

        Returns a `LatchHandle` on success, or `None` if blocked.
        """
        req = str(requester).strip() or "unknown"
        purp = str(purpose).strip()
        ttl = float(ttl_s)
        if ttl <= 0:
            ttl = 0.001

        now = time.monotonic()
        with self._mu:
            self._maybe_expire_locked(now_mono=now)

            if self._state is None:
                self._token_seq += 1
                token = self._token_seq
                self._state = LatchSnapshot(
                    name=self._name,
                    holder=req,
                    purpose=purp,
                    acquired_at_mono=now,
                    expires_at_mono=(now + ttl),
                    token=token,
                )
                return LatchHandle(self, token)

            # Blocked: log a clear message with holder and remaining TTL.
            remaining = max(0.0, self._state.expires_at_mono - now)
            logger.warning(
                "Latch blocked name=%s requester=%s holder=%s remaining_s=%.3f requester_purpose=%s holder_purpose=%s token=%s",
                self._name,
                req,
                self._state.holder,
                remaining,
                purp,
                self._state.purpose,
                self._state.token,
            )
            return None

    def release(self, token: int) -> bool:
        tok = int(token)
        now = time.monotonic()
        with self._mu:
            self._maybe_expire_locked(now_mono=now)
            if self._state is None:
                return False
            if self._state.token != tok:
                return False
            self._state = None
            return True


# Process-local latch for trade-intent emission coordination.
AGENT_INTENT_LATCH = InMemoryTtlLatch(name="agent_intent_emit")
