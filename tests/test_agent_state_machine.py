from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.common.agent_state_machine import AgentBackoff, AgentState, AgentStateMachine, trading_allowed


class _Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=float(seconds))


def test_init_to_ready_on_fresh_marketdata():
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    sm = AgentStateMachine(agent_id="test", now_fn=clock)

    assert sm.state == AgentState.INIT
    sm.on_marketdata(is_stale=False, meta={"test": True})
    assert sm.state == AgentState.READY


def test_marketdata_stale_to_degraded():
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    sm = AgentStateMachine(agent_id="test", now_fn=clock)
    sm.on_marketdata(is_stale=True)
    assert sm.state == AgentState.DEGRADED


def test_kill_switch_to_halted_and_not_overridden_by_marketdata():
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    sm = AgentStateMachine(agent_id="test", now_fn=clock)

    sm.on_kill_switch(enabled=True)
    assert sm.state == AgentState.HALTED

    # Marketdata signals must not override HALTED.
    sm.on_marketdata(is_stale=False)
    assert sm.state == AgentState.HALTED

    sm.recover()
    assert sm.state == AgentState.HALTED


def test_recover_to_ready_from_degraded():
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    sm = AgentStateMachine(agent_id="test", now_fn=clock)
    sm.on_marketdata(is_stale=True)
    assert sm.state == AgentState.DEGRADED

    sm.recover()
    assert sm.state == AgentState.READY


def test_unexpected_exception_to_error_with_backoff():
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    backoff = AgentBackoff(base_seconds=2.0, max_seconds=60.0, jitter=False)
    sm = AgentStateMachine(agent_id="test", now_fn=clock, backoff=backoff)

    st, delay = sm.on_unexpected_exception(exc=RuntimeError("boom"))
    assert st == AgentState.ERROR
    assert delay == 2.0
    assert sm.restart_not_before == clock.now + timedelta(seconds=2.0)
    assert sm.in_backoff() is True

    clock.advance(2.01)
    assert sm.in_backoff() is False


def test_trading_allowed_policy():
    allowed, reason = trading_allowed(state=AgentState.READY, agent_mode="LIVE", kill_switch_enabled=False)
    assert allowed is True
    assert reason == "ok"

    allowed, reason = trading_allowed(state=AgentState.DEGRADED, agent_mode="LIVE", kill_switch_enabled=False)
    assert allowed is False
    assert reason.startswith("agent_state_not_ready:")

    allowed, reason = trading_allowed(state=AgentState.READY, agent_mode="PAPER", kill_switch_enabled=False)
    assert allowed is False
    assert reason == "agent_mode_not_live"

    allowed, reason = trading_allowed(state=AgentState.READY, agent_mode="LIVE", kill_switch_enabled=True)
    assert allowed is False
    assert reason == "kill_switch_enabled"

