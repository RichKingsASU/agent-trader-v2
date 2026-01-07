from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Tuple


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentState(str, Enum):
    INIT = "INIT"
    IDLE = "IDLE"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    SHUTTING_DOWN = "SHUTTING_DOWN"


class AgentEvent(str, Enum):
    STARTUP = "STARTUP"
    HEARTBEAT_OK = "HEARTBEAT_OK"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    KILL_SWITCH_ON = "KILL_SWITCH_ON"
    KILL_SWITCH_OFF = "KILL_SWITCH_OFF"
    STRATEGY_CYCLE_START = "STRATEGY_CYCLE_START"
    STRATEGY_CYCLE_END = "STRATEGY_CYCLE_END"
    STRATEGY_CYCLE_SKIPPED = "STRATEGY_CYCLE_SKIPPED"
    ERROR = "ERROR"
    STOP = "STOP"


class InvalidTransition(ValueError):
    pass


@dataclass
class TransitionRecord:
    state_before: AgentState
    state_after: AgentState
    event: AgentEvent
    at: datetime
    reason_codes: list[str] = field(default_factory=list)


class StateMachine:
    """
    Minimal explicit agent state machine.

    Notes:
    - This is an OBSERVE-first contract: transitions are explicit and auditable.
    - Strategy/agent logic must stay unchanged; callers only wrap cycles with
      transition() + event emission.
    """

    # Allowed transitions (state, event) -> new state.
    _TRANSITIONS: Dict[Tuple[AgentState, AgentEvent], AgentState] = {
        # Startup / lifecycle
        (AgentState.INIT, AgentEvent.STARTUP): AgentState.IDLE,
        (AgentState.IDLE, AgentEvent.STOP): AgentState.SHUTTING_DOWN,
        (AgentState.HEALTHY, AgentEvent.STOP): AgentState.SHUTTING_DOWN,
        (AgentState.DEGRADED, AgentEvent.STOP): AgentState.SHUTTING_DOWN,
        (AgentState.HALTED, AgentEvent.STOP): AgentState.SHUTTING_DOWN,
        (AgentState.SHUTTING_DOWN, AgentEvent.STOP): AgentState.SHUTTING_DOWN,

        # Heartbeat-driven health
        (AgentState.IDLE, AgentEvent.HEARTBEAT_OK): AgentState.HEALTHY,
        (AgentState.IDLE, AgentEvent.HEARTBEAT_STALE): AgentState.DEGRADED,
        (AgentState.HEALTHY, AgentEvent.HEARTBEAT_OK): AgentState.HEALTHY,
        (AgentState.HEALTHY, AgentEvent.HEARTBEAT_STALE): AgentState.DEGRADED,
        (AgentState.DEGRADED, AgentEvent.HEARTBEAT_OK): AgentState.HEALTHY,
        (AgentState.DEGRADED, AgentEvent.HEARTBEAT_STALE): AgentState.DEGRADED,

        # Kill-switch safety
        (AgentState.INIT, AgentEvent.KILL_SWITCH_ON): AgentState.HALTED,
        (AgentState.IDLE, AgentEvent.KILL_SWITCH_ON): AgentState.HALTED,
        (AgentState.HEALTHY, AgentEvent.KILL_SWITCH_ON): AgentState.HALTED,
        (AgentState.DEGRADED, AgentEvent.KILL_SWITCH_ON): AgentState.HALTED,
        (AgentState.HALTED, AgentEvent.KILL_SWITCH_ON): AgentState.HALTED,
        (AgentState.HALTED, AgentEvent.KILL_SWITCH_OFF): AgentState.IDLE,

        # Error handling (fail-safe to DEGRADED unless explicitly HALTED)
        (AgentState.INIT, AgentEvent.ERROR): AgentState.DEGRADED,
        (AgentState.IDLE, AgentEvent.ERROR): AgentState.DEGRADED,
        (AgentState.HEALTHY, AgentEvent.ERROR): AgentState.DEGRADED,
        (AgentState.DEGRADED, AgentEvent.ERROR): AgentState.DEGRADED,
        (AgentState.HALTED, AgentEvent.ERROR): AgentState.HALTED,

        # Strategy cycle bookkeeping (no-op state, but auditable event history)
        (AgentState.IDLE, AgentEvent.STRATEGY_CYCLE_START): AgentState.IDLE,
        (AgentState.IDLE, AgentEvent.STRATEGY_CYCLE_END): AgentState.IDLE,
        (AgentState.IDLE, AgentEvent.STRATEGY_CYCLE_SKIPPED): AgentState.IDLE,
        (AgentState.HEALTHY, AgentEvent.STRATEGY_CYCLE_START): AgentState.HEALTHY,
        (AgentState.HEALTHY, AgentEvent.STRATEGY_CYCLE_END): AgentState.HEALTHY,
        (AgentState.HEALTHY, AgentEvent.STRATEGY_CYCLE_SKIPPED): AgentState.HEALTHY,
        (AgentState.DEGRADED, AgentEvent.STRATEGY_CYCLE_START): AgentState.DEGRADED,
        (AgentState.DEGRADED, AgentEvent.STRATEGY_CYCLE_END): AgentState.DEGRADED,
        (AgentState.DEGRADED, AgentEvent.STRATEGY_CYCLE_SKIPPED): AgentState.DEGRADED,
        (AgentState.HALTED, AgentEvent.STRATEGY_CYCLE_START): AgentState.HALTED,
        (AgentState.HALTED, AgentEvent.STRATEGY_CYCLE_END): AgentState.HALTED,
        (AgentState.HALTED, AgentEvent.STRATEGY_CYCLE_SKIPPED): AgentState.HALTED,
    }

    def __init__(self, *, initial_state: AgentState = AgentState.INIT) -> None:
        self.current_state: AgentState = AgentState(initial_state)
        self.last_transition_event: Optional[AgentEvent] = None
        self.last_transition_time: Optional[datetime] = None
        self.reason_codes: list[str] = []
        self._history: list[TransitionRecord] = []

    @property
    def history(self) -> Iterable[TransitionRecord]:
        return tuple(self._history)

    def transition(
        self, event: AgentEvent, context: Optional[MutableMapping[str, Any]] = None
    ) -> AgentState:
        """
        Transition the state machine based on an event.

        - Only explicit transitions are allowed.
        - Invalid transitions raise InvalidTransition with a clear message.
        - reason_codes are read from context (if provided) and stored as the
          latest reason_codes and recorded on the transition.
        """
        ev = AgentEvent(event)
        ctx: MutableMapping[str, Any] = context if context is not None else {}

        # Normalize/attach reason_codes.
        rc_raw = ctx.get("reason_codes")
        if rc_raw is None:
            reason_codes: list[str] = []
        elif isinstance(rc_raw, (list, tuple)):
            reason_codes = [str(x) for x in rc_raw if str(x)]
        else:
            reason_codes = [str(rc_raw)]
        ctx["reason_codes"] = reason_codes

        key = (self.current_state, ev)
        if key not in self._TRANSITIONS:
            allowed = sorted(
                {e.value for (s, e), _ns in self._TRANSITIONS.items() if s == self.current_state}
            )
            raise InvalidTransition(
                f"Invalid transition: state={self.current_state.value} event={ev.value}. "
                f"Allowed events from {self.current_state.value}: {allowed}"
            )

        before = self.current_state
        after = self._TRANSITIONS[key]
        now = _utc_now()

        self.current_state = after
        self.last_transition_event = ev
        self.last_transition_time = now
        self.reason_codes = list(reason_codes)
        self._history.append(
            TransitionRecord(
                state_before=before,
                state_after=after,
                event=ev,
                at=now,
                reason_codes=list(reason_codes),
            )
        )
        return self.current_state

