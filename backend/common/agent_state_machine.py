from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentState(str, Enum):
    INIT = "INIT"
    READY = "READY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class StateTransition:
    agent_id: str
    from_state: AgentState
    to_state: AgentState
    trigger: str
    at: datetime
    reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_log_event(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "trigger": self.trigger,
            "at": self.at.isoformat(),
            "reason": self.reason,
            "meta": self.meta,
        }


@dataclass(frozen=True)
class AgentBackoff:
    """
    Exponential backoff helper for ERROR state.

    Uses "full jitter" (random uniform in [0, cap]) by default.
    """

    base_seconds: float = 1.0
    max_seconds: float = 60.0
    jitter: bool = True

    def next_delay_s(self, *, error_count: int) -> float:
        if error_count <= 0:
            return 0.0
        cap = min(self.max_seconds, self.base_seconds * (2 ** (error_count - 1)))
        if cap <= 0:
            return 0.0
        return random.random() * cap if self.jitter else cap


class AgentStateMachine:
    """
    Small, explicit execution-agent state machine.

    States:
      INIT, READY, DEGRADED, HALTED, ERROR

    Transitions:
      marketdata stale => DEGRADED
      kill-switch => HALTED
      recover => READY
      unexpected exception => ERROR (optional exponential backoff for restart)
    """

    def __init__(
        self,
        *,
        agent_id: str,
        now_fn: Callable[[], datetime] = _utc_now,
        backoff: AgentBackoff | None = None,
    ) -> None:
        self._agent_id = str(agent_id)
        self._now = now_fn
        self._backoff = backoff or AgentBackoff()

        self._state: AgentState = AgentState.INIT
        self._last_transition_at: datetime = self._now()

        self._error_count: int = 0
        self._restart_not_before: datetime | None = None
        self._last_error: str | None = None

        # Emit initial state as a transition-like log event for observability.
        self._emit_transition(
            from_state=AgentState.INIT,
            to_state=AgentState.INIT,
            trigger="init",
            reason=None,
            meta={},
        )

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def last_transition_at(self) -> datetime:
        return self._last_transition_at

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def restart_not_before(self) -> datetime | None:
        return self._restart_not_before

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _emit_transition(
        self,
        *,
        from_state: AgentState,
        to_state: AgentState,
        trigger: str,
        reason: str | None,
        meta: dict[str, Any],
    ) -> None:
        t = StateTransition(
            agent_id=self._agent_id,
            from_state=from_state,
            to_state=to_state,
            trigger=str(trigger),
            at=self._now(),
            reason=reason,
            meta=dict(meta or {}),
        )
        logger.info("agent.state_transition %s", json.dumps(t.to_log_event(), separators=(",", ":")))

    def transition(
        self,
        *,
        to_state: AgentState,
        trigger: str,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AgentState:
        to_state = AgentState(to_state)
        if to_state == self._state:
            return self._state
        prev = self._state
        self._state = to_state
        self._last_transition_at = self._now()
        self._emit_transition(
            from_state=prev,
            to_state=to_state,
            trigger=trigger,
            reason=reason,
            meta=meta or {},
        )
        return self._state

    def on_kill_switch(self, *, enabled: bool, meta: dict[str, Any] | None = None) -> AgentState:
        if enabled:
            return self.transition(
                to_state=AgentState.HALTED,
                trigger="kill_switch",
                reason="kill_switch_enabled",
                meta=meta,
            )
        return self._state

    def on_marketdata(self, *, is_stale: bool, meta: dict[str, Any] | None = None) -> AgentState:
        if is_stale:
            # Do not override HALTED (explicit manual/ops stop) with DEGRADED.
            if self._state == AgentState.HALTED:
                return self._state
            return self.transition(
                to_state=AgentState.DEGRADED,
                trigger="marketdata_stale",
                reason="marketdata_stale",
                meta=meta,
            )

        # Market data is fresh: allow recovery to READY if we were DEGRADED/INIT/ERROR.
        if self._state in {AgentState.INIT, AgentState.DEGRADED}:
            return self.transition(
                to_state=AgentState.READY,
                trigger="recover",
                reason="marketdata_fresh",
                meta=meta,
            )
        return self._state

    def recover(self, *, reason: str = "manual_recover", meta: dict[str, Any] | None = None) -> AgentState:
        # Explicit operator recovery. Does not override kill-switch HALTED.
        if self._state == AgentState.HALTED:
            return self._state
        # Clear error/backoff on recover.
        self._restart_not_before = None
        self._last_error = None
        self._error_count = 0
        return self.transition(to_state=AgentState.READY, trigger="recover", reason=reason, meta=meta)

    def on_unexpected_exception(
        self,
        *,
        exc: BaseException,
        meta: dict[str, Any] | None = None,
    ) -> tuple[AgentState, float]:
        """
        Transition to ERROR and compute an optional backoff delay.

        Returns: (state, backoff_seconds)
        """
        self._error_count += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        delay_s = self._backoff.next_delay_s(error_count=self._error_count)
        self._restart_not_before = self._now() + timedelta(seconds=float(delay_s)) if delay_s > 0 else None

        # ERROR overrides DEGRADED/READY/INIT, but not HALTED.
        if self._state != AgentState.HALTED:
            self.transition(
                to_state=AgentState.ERROR,
                trigger="unexpected_exception",
                reason="unexpected_exception",
                meta={
                    **(meta or {}),
                    "error": self._last_error,
                    "error_count": self._error_count,
                    "backoff_seconds": delay_s,
                    "restart_not_before": self._restart_not_before.isoformat() if self._restart_not_before else None,
                },
            )
        return (self._state, delay_s)

    def in_backoff(self) -> bool:
        if self._restart_not_before is None:
            return False
        return self._now() < self._restart_not_before


def read_agent_mode() -> str:
    """
    Agent execution mode. Convention:
      - LIVE: live trading is allowed (subject to state/kill-switch)
      - anything else: live trading is refused
    """
    return str(os.getenv("AGENT_MODE") or "").strip().upper() or "UNKNOWN"


def trading_allowed(
    *,
    state: AgentState,
    agent_mode: str,
    kill_switch_enabled: bool,
) -> tuple[bool, str]:
    """
    Policy gate:
      Must be READY + AGENT_MODE=LIVE + kill-switch OFF.
    """
    if kill_switch_enabled:
        return (False, "kill_switch_enabled")
    if str(agent_mode).strip().upper() != "LIVE":
        return (False, "agent_mode_not_live")
    if state != AgentState.READY:
        return (False, f"agent_state_not_ready:{state.value}")
    return (True, "ok")

