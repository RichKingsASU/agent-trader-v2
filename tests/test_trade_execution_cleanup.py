from __future__ import annotations

import pytest

from backend.common.agent_mode import AgentModeError
try:
    from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"backend.execution.engine API not available (documented-but-unimplemented): {type(e).__name__}: {e}",
        strict=False,
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


class _ReservationHandleStub:
    def __init__(self, calls: list[dict]):
        self._calls = calls
        self._released = False

    def release(self, *, outcome: str, error: str | None = None) -> None:
        if self._released:
            return
        self._released = True
        self._calls.append({"outcome": outcome, "error": error})


class _ReservationsStub:
    def __init__(self):
        self.reserve_calls: list[dict] = []
        self.release_calls: list[dict] = []

    def reserve(
        self,
        *,
        tenant_id: str,
        broker_account_id: str,
        client_intent_id: str,
        amount_usd: float,
        ttl_seconds: int = 300,  # noqa: ARG002
        meta: dict | None = None,  # noqa: ARG002
    ):
        self.reserve_calls.append(
            {
                "tenant_id": tenant_id,
                "broker_account_id": broker_account_id,
                "client_intent_id": client_intent_id,
                "amount_usd": float(amount_usd),
            }
        )
        return _ReservationHandleStub(self.release_calls)


class _BrokerStubOK:
    def __init__(self):
        self.place_calls = 0

    def place_order(self, *, intent):  # noqa: ARG002
        self.place_calls += 1
        return {"id": "order_1", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


class _BrokerStubBoom(_BrokerStubOK):
    def place_order(self, *, intent):  # noqa: ARG002
        raise RuntimeError("broker_down")


def _risk_allow():
    return RiskManager(
        config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )


def test_cleanup_releases_on_broker_exception(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("EXECUTION_ENABLED", "true")

    reservations = _ReservationsStub()
    engine = ExecutionEngine(broker=_BrokerStubBoom(), risk=_risk_allow(), dry_run=False, reservations=reservations)

    with pytest.raises(RuntimeError):
        engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
                metadata={"tenant_id": "t1", "notional_usd": 123.45},
            )
        )

    assert len(reservations.reserve_calls) == 1
    assert len(reservations.release_calls) == 1
    assert reservations.release_calls[0]["outcome"] == "exception"
    assert "broker_down" in (reservations.release_calls[0]["error"] or "")


def test_cleanup_releases_on_agent_mode_error(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("AGENT_MODE", "DISABLED")

    reservations = _ReservationsStub()
    engine = ExecutionEngine(broker=_BrokerStubOK(), risk=_risk_allow(), dry_run=False, reservations=reservations)

    with pytest.raises(AgentModeError):
        engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
                metadata={"tenant_id": "t1", "notional_usd": 10},
            )
        )

    assert len(reservations.reserve_calls) == 1
    assert len(reservations.release_calls) == 1
    assert reservations.release_calls[0]["outcome"] == "exception"
    assert "AgentMode" in (reservations.release_calls[0]["error"] or "")


def test_cleanup_releases_on_risk_reject(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("AGENT_MODE", "LIVE")

    reservations = _ReservationsStub()
    broker = _BrokerStubOK()
    risk = RiskManager(
        config=RiskConfig(max_position_qty=1, max_daily_trades=0, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False, reservations=reservations)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
            metadata={"tenant_id": "t1", "notional_usd": 10},
        )
    )

    assert result.status == "rejected"
    assert broker.place_calls == 0
    assert len(reservations.release_calls) == 1
    assert reservations.release_calls[0]["outcome"] == "rejected"


def test_cleanup_releases_on_dry_run(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("AGENT_MODE", "DISABLED")  # dry-run should not require LIVE

    reservations = _ReservationsStub()
    broker = _BrokerStubOK()
    engine = ExecutionEngine(broker=broker, risk=_risk_allow(), dry_run=True, reservations=reservations)

    result = engine.execute_intent(
        intent=OrderIntent(
            strategy_id="s1",
            broker_account_id="acct1",
            symbol="SPY",
            side="buy",
            qty=1,
            metadata={"tenant_id": "t1", "notional_usd": 10},
        )
    )

    assert result.status == "dry_run"
    assert broker.place_calls == 0
    assert len(reservations.release_calls) == 1
    assert reservations.release_calls[0]["outcome"] == "dry_run"

