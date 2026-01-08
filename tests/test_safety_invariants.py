"""
Invariant-focused safety tests.

Goal: validate safety rules (not profits) without live APIs or market data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.execution.engine import OrderIntent, RiskConfig, RiskManager


# Import backtesting primitives without invoking any Alpaca client code.
# (functions/ is not a package; mirror existing tests that add it to sys.path.)
def _import_backtest_account():
    import sys

    functions_dir = Path(__file__).resolve().parent.parent / "functions"
    sys.path.insert(0, str(functions_dir))
    from backtester import BacktestAccount  # type: ignore

    return BacktestAccount


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = int(trades_today)

    def count_trades_today(self, *, broker_account_id: str, trading_date: str):  # noqa: ARG002
        return int(self._trades_today)


class _PositionsStub:
    def __init__(self, qty: float):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


def test_capital_never_goes_negative_on_failed_entries():
    """
    Invariant: capital (cash) must never go negative.

    BacktestAccount.open_position must refuse trades that would overspend cash.
    """
    BacktestAccount = _import_backtest_account()
    account = BacktestAccount(Decimal("1000"))
    t0 = datetime(2024, 1, 1, 9, 30)

    # Overspend attempt must fail and must not change cash.
    ok = account.open_position(
        symbol="SPY",
        quantity=Decimal("100"),
        price=Decimal("50"),  # cost=5000 > 1000
        timestamp=t0,
        side="long",
    )
    assert ok is False
    assert account.cash == Decimal("1000")
    assert account.cash >= 0


def test_capital_never_goes_negative_in_equity_curve_mark_to_market():
    """
    Invariant: equity and cash must stay >= 0 under mark-to-market updates.

    This test uses deterministic, local prices (no market data).
    """
    BacktestAccount = _import_backtest_account()
    account = BacktestAccount(Decimal("1000"))
    t0 = datetime(2024, 1, 1, 9, 30)

    # Spend all cash exactly: cash becomes 0 but must not go negative.
    ok = account.open_position(
        symbol="SPY",
        quantity=Decimal("100"),
        price=Decimal("10"),  # cost=1000
        timestamp=t0,
        side="long",
    )
    assert ok is True
    assert account.cash == Decimal("0")
    assert account.cash >= 0

    # Mark-to-market through a crash to zero.
    for i, px in enumerate([Decimal("10"), Decimal("5"), Decimal("0")]):
        account.record_equity(t0 + timedelta(minutes=i), px)

    equities = [point["equity"] for point in account.equity_curve]
    cashes = [point["cash"] for point in account.equity_curve]
    assert min(equities) >= 0.0
    assert min(cashes) >= 0.0


@pytest.mark.parametrize(
    "side,qty,expected_allowed",
    [
        ("buy", 5, True),   # exactly at cap
        ("buy", 6, False),  # exceeds cap
        ("sell", 5, True),  # exactly at cap (short)
        ("sell", 6, False),  # exceeds cap (short)
    ],
)
def test_risk_cap_never_exceeded_by_projected_position(side: str, qty: float, expected_allowed: bool, monkeypatch):
    """
    Invariant: risk cap must never be exceeded.

    For execution, the risk cap is enforced as:
      abs(projected_position_qty) <= max_position_qty

    This test uses in-memory stubs only (no Postgres, no Firestore, no broker).
    """
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXECUTION_HALTED_FILE", raising=False)

    risk = RiskManager(
        config=RiskConfig(max_position_qty=5, max_daily_trades=999, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )
    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side=side,
        qty=qty,
    )
    decision = risk.validate(intent=intent)

    assert decision.allowed is expected_allowed
    if expected_allowed:
        # Assert the invariant explicitly using the recorded check payload.
        chk = next(c for c in decision.checks if c.get("check") == "max_position_size")
        assert abs(float(chk["projected_qty"])) <= float(chk["limit_abs_qty"])
    else:
        assert decision.reason == "max_position_size_exceeded"

