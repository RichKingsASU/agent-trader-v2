from backend.execution.engine import (
    ExecutionEngine,
    OrderIntent,
    RiskConfig,
    RiskManager,
)
from backend.common.agent_mode import AgentModeError
from datetime import datetime, timezone


def _fixed_utc(dt: datetime):
    if dt.tzinfo is None:
        raise AssertionError("test requires tz-aware utc datetime")
    return dt.astimezone(timezone.utc)


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


def test_market_open_delay_blocks_by_default(monkeypatch):
    """
    Block real EQUITY trading during first DEFAULT minutes after 09:30 NY open.
    """
    monkeypatch.delenv("MARKET_OPEN_TRADE_DELAY_MINUTES", raising=False)
    monkeypatch.delenv("MARKET_OPEN_TRADE_DELAY_DISABLED", raising=False)
    monkeypatch.delenv("DISABLE_MARKET_OPEN_TRADE_DELAY", raising=False)
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)

    # 2026-01-14 is a Wednesday. 09:32 NY == 14:32 UTC (EST).
    monkeypatch.setattr(
        "backend.execution.engine._utc_now",
        lambda: _fixed_utc(datetime(2026, 1, 14, 14, 32, 0, tzinfo=timezone.utc)),
    )

    broker = _BrokerStub()
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
            asset_class="EQUITY",
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "market_open_delay"
    assert broker.place_calls == 0
    checks = list(result.risk.checks or [])
    assert any(c.get("check") == "market_open_delay" and c.get("delay_minutes") == 5 for c in checks)


def test_market_open_delay_respects_minutes_override(monkeypatch):
    monkeypatch.setenv("MARKET_OPEN_TRADE_DELAY_MINUTES", "15")
    monkeypatch.delenv("MARKET_OPEN_TRADE_DELAY_DISABLED", raising=False)
    monkeypatch.delenv("DISABLE_MARKET_OPEN_TRADE_DELAY", raising=False)
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)

    # 09:40 NY == 14:40 UTC (still within 15m window)
    monkeypatch.setattr(
        "backend.execution.engine._utc_now",
        lambda: _fixed_utc(datetime(2026, 1, 14, 14, 40, 0, tzinfo=timezone.utc)),
    )

    broker = _BrokerStub()
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
            asset_class="EQUITY",
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "market_open_delay"
    assert broker.place_calls == 0
    checks = list(result.risk.checks or [])
    assert any(c.get("check") == "market_open_delay" and c.get("delay_minutes") == 15 for c in checks)


def test_market_open_delay_can_be_disabled_via_env(monkeypatch):
    """
    When disabled, the request should pass the market-open gate and be rejected later by kill switch.
    This avoids exercising the full pre-trade assertion stack (marketdata + Firestore).
    """
    monkeypatch.setenv("MARKET_OPEN_TRADE_DELAY_DISABLED", "1")
    monkeypatch.delenv("MARKET_OPEN_TRADE_DELAY_MINUTES", raising=False)
    monkeypatch.delenv("DISABLE_MARKET_OPEN_TRADE_DELAY", raising=False)
    monkeypatch.setenv("EXECUTION_HALTED", "1")

    # Within the normal delay window.
    monkeypatch.setattr(
        "backend.execution.engine._utc_now",
        lambda: _fixed_utc(datetime(2026, 1, 14, 14, 32, 0, tzinfo=timezone.utc)),
    )

    broker = _BrokerStub()
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
            asset_class="EQUITY",
        )
    )
    assert result.status == "rejected"
    assert result.risk.reason == "kill_switch_enabled"
    assert broker.place_calls == 0

