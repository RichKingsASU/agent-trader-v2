"""
Kill-switch persistence semantics tests.

Validates:
- File-based kill switch survives restart
- Env-based kill switch overrides defaults
- Clearing requires explicit operator action
- No execution resumes automatically
"""

from __future__ import annotations

import importlib

import pytest

import backend.common.kill_switch as ks
from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = int(trades_today)

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        raise AssertionError("ledger writes should not be called in these tests")


class _PositionsStub:
    def __init__(self, qty: float = 0.0):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


class _BrokerStub:
    def __init__(self):
        self.place_calls = 0

    def place_order(self, *, intent):  # noqa: ARG002
        self.place_calls += 1
        return {"id": "order_1", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


def test_file_based_kill_switch_survives_restart_and_blocks_until_explicit_clear(tmp_path, monkeypatch):
    p = tmp_path / "EXECUTION_HALTED"
    p.write_text("1\n", encoding="utf-8")

    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXECUTION_HALTED_FILE", str(p))

    # Simulate a "restart": module reload forces callers to re-evaluate config.
    importlib.reload(ks)
    with pytest.raises(ks.ExecutionHaltedError):
        ks.require_live_mode(operation="unit-test-op")

    # "Restart" again: should still be halted because the file persists.
    importlib.reload(ks)
    for _ in range(3):
        with pytest.raises(ks.ExecutionHaltedError):
            ks.require_live_mode(operation="unit-test-op")

    # Explicit operator action: change the mounted file to a falsey value.
    p.write_text("0\n", encoding="utf-8")
    importlib.reload(ks)
    ks.require_live_mode(operation="unit-test-op")  # should not raise


def test_env_based_kill_switch_overrides_file_allow_state(tmp_path, monkeypatch):
    p = tmp_path / "EXECUTION_HALTED"
    p.write_text("0\n", encoding="utf-8")

    monkeypatch.setenv("EXECUTION_HALTED_FILE", str(p))
    monkeypatch.setenv("EXECUTION_HALTED", "1")
    importlib.reload(ks)

    enabled, source = ks.get_kill_switch_state()
    assert enabled is True
    assert source == f"env:{ks.KILL_SWITCH_ENV}"

    with pytest.raises(ks.ExecutionHaltedError):
        ks.require_live_mode(operation="unit-test-op")

    # Explicit operator action: clear the env var.
    monkeypatch.setenv("EXECUTION_HALTED", "0")
    importlib.reload(ks)

    enabled, source = ks.get_kill_switch_state()
    assert enabled is False
    assert source is None
    ks.require_live_mode(operation="unit-test-op")  # should not raise


def test_clearing_env_does_not_clear_file_kill_switch(tmp_path, monkeypatch):
    p = tmp_path / "EXECUTION_HALTED"
    p.write_text("true\n", encoding="utf-8")

    monkeypatch.setenv("EXECUTION_HALTED_FILE", str(p))
    monkeypatch.setenv("EXECUTION_HALTED", "1")
    importlib.reload(ks)
    assert ks.is_kill_switch_enabled() is True

    # Clearing env does not change the persisted file halt state.
    monkeypatch.setenv("EXECUTION_HALTED", "0")
    importlib.reload(ks)
    enabled, source = ks.get_kill_switch_state()
    assert enabled is True
    assert source == f"file:{p}"
    with pytest.raises(ks.ExecutionHaltedError):
        ks.require_live_mode(operation="unit-test-op")


def test_no_execution_resumes_automatically_across_engine_restart(tmp_path, monkeypatch):
    p = tmp_path / "EXECUTION_HALTED"
    p.write_text("1\n", encoding="utf-8")

    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXECUTION_HALTED_FILE", str(p))

    def _make_engine(broker: _BrokerStub) -> ExecutionEngine:
        risk = RiskManager(
            config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
            ledger=_LedgerStub(trades_today=0),
            positions=_PositionsStub(qty=0),
        )
        return ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    broker1 = _BrokerStub()
    engine1 = _make_engine(broker1)
    result1 = engine1.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result1.status == "rejected"
    assert result1.risk.reason == "kill_switch_enabled"
    assert broker1.place_calls == 0

    # Simulated restart: new engine instance must still refuse to trade.
    broker2 = _BrokerStub()
    engine2 = _make_engine(broker2)
    result2 = engine2.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result2.status == "rejected"
    assert result2.risk.reason == "kill_switch_enabled"
    assert broker2.place_calls == 0

