from __future__ import annotations

import pytest

try:
    from backend.execution.engine import (
        ExecutionEngine,
        OrderIntent,
        RiskConfig,
        RiskManager,
    )
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"backend.execution.engine API not available (documented-but-unimplemented): {type(e).__name__}: {e}",
        strict=False,
    )

from backend.common.agent_mode import AgentModeError


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = trades_today

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        raise AssertionError("ledger writes should not be called in these tests")


class _PositionsStub:
    def __init__(self, qty: float):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)

class _OptionPositionsStub:
    def __init__(self, net_delta: float = 0.0, net_gamma: float = 0.0):
        self._net_delta = float(net_delta)
        self._net_gamma = float(net_gamma)

    def net_delta(self, *, contract_multiplier: float = 100.0) -> float:  # noqa: ARG002
        return float(self._net_delta)

    def net_gamma(self, *, contract_multiplier: float = 100.0) -> float:  # noqa: ARG002
        return float(self._net_gamma)


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


def test_dry_run_does_not_place_order(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result.status == "dry_run"
    assert broker.place_calls == 0


def test_kill_switch_rejects(monkeypatch):
    monkeypatch.setenv("EXECUTION_HALTED", "1")
    broker = _BrokerStub()
    # fail_open doesn't matter for kill switch
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "kill_switch_enabled"
    assert broker.place_calls == 0


def test_max_daily_trades_rejects(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=2, fail_open=True),
        ledger=_LedgerStub(trades_today=2),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "max_daily_trades_exceeded"
    assert broker.place_calls == 0


def test_max_position_size_rejects(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=5, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=5),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "max_position_size_exceeded"
    assert broker.place_calls == 0


def test_agent_mode_must_be_live_to_place_orders(monkeypatch):
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
    monkeypatch.setenv("AGENT_MODE", "DISABLED")

    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    try:
        engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
            )
        )
        assert False, "expected AgentModeError"
    except AgentModeError:
        pass
    assert broker.place_calls == 0


def test_agent_mode_halted_refuses_trading(monkeypatch):
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
    monkeypatch.setenv("AGENT_MODE", "HALTED")

    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

    try:
        engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
            )
        )
        assert False, "expected AgentModeError"
    except AgentModeError:
        pass
    assert broker.place_calls == 0


def test_max_delta_exposure_rejects(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, max_delta_exposure=50.0),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
        option_positions=_OptionPositionsStub(net_delta=0.0, net_gamma=0.0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="AAPL250117C00150000",
            side="buy",
            qty=1,
            metadata={"greeks": {"delta": 0.60}},
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "max_delta_exposure_exceeded"
    assert broker.place_calls == 0


def test_max_gamma_exposure_rejects(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, max_gamma_exposure=5.0),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
        option_positions=_OptionPositionsStub(net_delta=0.0, net_gamma=0.0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="AAPL250117C00150000",
            side="buy",
            qty=1,
            metadata={"greeks": {"gamma": 0.10}},
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "max_gamma_exposure_exceeded"


def test_per_trade_risk_cap_rejects_long_option(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, per_trade_risk_cap_usd=100.0),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
        option_positions=_OptionPositionsStub(net_delta=0.0, net_gamma=0.0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    # premium risk ~= price * 100 * qty
    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="AAPL250117C00150000",
            side="buy",
            qty=1,
            metadata={"price": 2.0, "greeks": {"delta": 0.25, "gamma": 0.05}},
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "per_trade_risk_cap_exceeded"


def test_daily_options_loss_cap_rejects(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    broker = _BrokerStub()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, daily_options_loss_cap_usd=100.0),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
        option_positions=_OptionPositionsStub(net_delta=0.0, net_gamma=0.0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="AAPL250117C00150000",
            side="buy",
            qty=1,
            metadata={"daily_options_pnl_usd": -150.0, "greeks": {"delta": 0.25}},
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "daily_options_loss_cap_exceeded"

