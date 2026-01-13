import threading
import time

import pytest

from backend.common.kill_switch import ExecutionHaltedError
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.execution.engine import AlpacaBroker, OrderIntent


def _minimal_intent() -> OrderIntent:
    return OrderIntent(
        strategy_id="race_test_strategy",
        broker_account_id="race_test_account",
        symbol="SPY",
        side="buy",
        qty=1,
        client_intent_id="race_test_intent_id",
        metadata={},
    )


def _configure_alpaca_env(monkeypatch) -> None:
    # Broker init reads these at construction time.
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")


def test_env_vars_mutate_between_checks_execution_blocked_and_fatal_wins(monkeypatch):
    """
    Simulate:
    - TRADING_MODE is 'paper' at T0 (passes paper override)
    - TRADING_MODE flips to 'live' between preflight checks

    Assert:
    - No HTTP side effect occurs
    - fatal_if_execution_reached wins (FatalExecutionPathError)
    """
    _configure_alpaca_env(monkeypatch)
    monkeypatch.setenv("EXECUTION_HALTED", "0")

    import backend.execution.engine as engine_mod

    http_called = threading.Event()

    def _deny_http(*_a, **_kw):
        http_called.set()
        raise AssertionError("HTTP side effect should not occur under race simulation")

    monkeypatch.setattr(engine_mod.requests, "post", _deny_http)

    first_mode_check_done = threading.Event()
    allow_second_mode_check = threading.Event()
    mode_calls = {"n": 0}
    real_getenv = engine_mod.os.getenv

    def getenv_racy(name: str, default=None):
        if name != "TRADING_MODE":
            return real_getenv(name, default)
        mode_calls["n"] += 1
        if mode_calls["n"] == 1:
            first_mode_check_done.set()
            return "paper"
        # Block until test flips the value, then return non-paper.
        allow_second_mode_check.wait(timeout=2.0)
        return "live"

    monkeypatch.setattr(engine_mod.os, "getenv", getenv_racy)

    broker = AlpacaBroker(request_timeout_s=0.01)
    intent = _minimal_intent()

    caught: list[BaseException] = []

    def _runner():
        try:
            broker.place_order(intent=intent)
        except BaseException as e:  # noqa: BLE001 - test harness
            caught.append(e)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    assert first_mode_check_done.wait(timeout=2.0), "did not reach first TRADING_MODE check"
    allow_second_mode_check.set()
    t.join(timeout=2.0)

    assert caught, "expected an exception"
    assert isinstance(caught[0], FatalExecutionPathError)
    assert not http_called.is_set()


def test_kill_switch_flips_mid_execution_blocks_before_http(monkeypatch):
    """
    Simulate:
    - kill switch OFF at first preflight
    - kill switch flips ON between preflight checks

    Assert:
    - execution is blocked (ExecutionHaltedError)
    - no HTTP side effect occurs
    """
    _configure_alpaca_env(monkeypatch)
    monkeypatch.setenv("TRADING_MODE", "paper")  # paper override would otherwise allow HTTP

    import backend.execution.engine as engine_mod
    import backend.common.kill_switch as ks_mod

    http_called = threading.Event()

    def _deny_http(*_a, **_kw):
        http_called.set()
        raise AssertionError("HTTP side effect should not occur when kill switch flips")

    monkeypatch.setattr(engine_mod.requests, "post", _deny_http)

    first_kill_check_done = threading.Event()
    allow_second_kill_check = threading.Event()
    kill_calls = {"n": 0}

    def get_kill_switch_state_racy():
        kill_calls["n"] += 1
        if kill_calls["n"] == 1:
            first_kill_check_done.set()
            return False, None
        allow_second_kill_check.wait(timeout=2.0)
        return True, "env:EXECUTION_HALTED"

    monkeypatch.setattr(ks_mod, "get_kill_switch_state", get_kill_switch_state_racy)

    broker = AlpacaBroker(request_timeout_s=0.01)
    intent = _minimal_intent()

    caught: list[BaseException] = []

    def _runner():
        try:
            broker.place_order(intent=intent)
        except BaseException as e:  # noqa: BLE001 - test harness
            caught.append(e)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    assert first_kill_check_done.wait(timeout=2.0), "did not reach first kill-switch check"
    allow_second_kill_check.set()
    t.join(timeout=2.0)

    assert caught, "expected an exception"
    assert isinstance(caught[0], ExecutionHaltedError)
    assert not http_called.is_set()


def test_token_valid_at_t0_revoked_at_t1_blocks_before_execution(monkeypatch):
    """
    Simulate:
    - Token verifies at T0
    - Token is revoked at T1 (time advances)

    Assert:
    - second verification fails (blocked)
    - "execution" sentinel is never reached

    Notes:
    - This test uses time mocking + threads to make the race deterministic.
    - It intentionally models a double-check pattern (check-then-use) to ensure
      a revocation between checks fails closed.
    """
    import backend.common.execution_confirm as confirm_mod
    import backend.common.runtime_execution_prevention as rep_mod

    class _Clock:
        def __init__(self, t: float):
            self.t = t

        def time(self) -> float:
            return self.t

    clock = _Clock(t=0.0)
    monkeypatch.setattr(time, "time", clock.time)

    token_revoked_at = 1.0
    first_check_done = threading.Event()
    allow_second_check = threading.Event()
    execution_reached = threading.Event()

    # If execution is reached, the safety boundary should fire; we assert we never get there.
    def fatal_never(*_a, **_kw):
        execution_reached.set()
        raise AssertionError("execution should be blocked before fatal boundary is reached")

    monkeypatch.setattr(rep_mod, "fatal_if_execution_reached", fatal_never)

    # Confirmation token: valid at T0, revoked at T1 by clearing env.
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "tok")

    caught: list[BaseException] = []

    def _runner():
        try:
            # check @ T0 (token present + matches)
            confirm_mod.require_confirm_token_for_live_execution(provided_token="tok")
            first_check_done.set()
            allow_second_check.wait(timeout=2.0)
            # "use" step also checks token (should fail closed after revocation)
            confirm_mod.require_confirm_token_for_live_execution(provided_token="tok")
            rep_mod.fatal_if_execution_reached(operation="execution", explicit_message="should_not_reach")
        except BaseException as e:  # noqa: BLE001 - test harness
            caught.append(e)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    assert first_check_done.wait(timeout=2.0), "did not reach first token check"
    clock.t = 2.0  # advance beyond revocation time
    if clock.t >= token_revoked_at:
        monkeypatch.delenv("EXECUTION_CONFIRM_TOKEN", raising=False)
    allow_second_check.set()
    t.join(timeout=2.0)

    assert caught, "expected an exception"
    assert isinstance(caught[0], confirm_mod.ExecutionConfirmTokenError)
    assert not execution_reached.is_set()

