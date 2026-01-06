from backend.execution.engine import (
    ExecutionEngine,
    OrderIntent,
    RiskConfig,
    RiskManager,
)


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

