from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager


class _LedgerStub:
    def count_trades_today(self, **kwargs):  # noqa: ARG002
        return 0

    def write_fill(self, **kwargs):  # noqa: ARG002
        raise AssertionError("ledger writes should not be called in these tests")


class _PositionsStub:
    def get_position_qty(self, **kwargs):  # noqa: ARG002
        return 0.0


class _BrokerStub:
    def place_order(self, **kwargs):  # noqa: ARG002
        return {"id": "order_1", "status": "new", "filled_qty": "0"}

    def cancel_order(self, **kwargs):  # noqa: ARG002
        return {"id": "order_1", "status": "canceled"}

    def get_order_status(self, **kwargs):  # noqa: ARG002
        return {"id": "order_1", "status": "new", "filled_qty": "0"}


def test_agent_budget_caps_executions(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_ENABLED", "true")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_USE_FIRESTORE", "false")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_JSON", '{"s1":{"max_daily_executions":1}}')

    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, market_open_trade_block_minutes=0),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )
    engine = ExecutionEngine(broker=_BrokerStub(), risk=risk, dry_run=True)

    intent = OrderIntent(strategy_id="s1", broker_account_id="acct1", symbol="SPY", side="buy", qty=1)

    r1 = engine.execute_intent(intent=intent)
    assert r1.status == "dry_run"
    assert r1.risk.allowed is True

    r2 = engine.execute_intent(intent=intent)
    assert r2.status == "rejected"
    assert r2.risk.allowed is False
    assert r2.risk.reason == "agent_execution_budget_exceeded"


def test_agent_budget_caps_daily_capital_pct(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_ENABLED", "true")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_USE_FIRESTORE", "false")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_JSON", '{"s1":{"max_daily_capital_pct":0.10}}')

    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, market_open_trade_block_minutes=0),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )
    engine = ExecutionEngine(broker=_BrokerStub(), risk=risk, dry_run=True)

    i1 = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={"daily_capital_usd": 1000, "notional_usd": 60},
    )
    i2 = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={"daily_capital_usd": 1000, "notional_usd": 50},
    )

    r1 = engine.execute_intent(intent=i1)
    assert r1.status == "dry_run"
    assert r1.risk.allowed is True

    r2 = engine.execute_intent(intent=i2)
    assert r2.status == "rejected"
    assert r2.risk.allowed is False
    assert r2.risk.reason == "agent_execution_budget_exceeded"


def test_agent_budget_fail_closed_when_capital_missing(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_ENABLED", "true")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_USE_FIRESTORE", "false")
    monkeypatch.setenv("EXEC_AGENT_BUDGETS_JSON", '{"s1":{"max_daily_capital_pct":0.10}}')

    risk = RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True, market_open_trade_block_minutes=0),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )
    engine = ExecutionEngine(broker=_BrokerStub(), risk=risk, dry_run=True)

    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={"notional_usd": 10},
    )

    r = engine.execute_intent(intent=intent)
    assert r.status == "rejected"
    assert r.risk.allowed is False
    assert r.risk.reason == "agent_budget_state_unavailable"

