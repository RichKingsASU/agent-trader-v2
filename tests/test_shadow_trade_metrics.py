from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from backend.strategy_service.shadow_metrics import (
    compute_max_drawdown_from_realized_pnls,
    compute_shadow_metrics,
    compute_trade_pnl,
)


def test_compute_trade_pnl_long_buy_profit_and_percent() -> None:
    pnl, pct = compute_trade_pnl(entry_price="100.00", current_price="110.00", quantity="2", side="BUY")
    assert pnl == Decimal("20.00")
    assert pct == Decimal("10.00")  # 20 / 200 * 100


def test_compute_trade_pnl_short_sell_profit_and_percent() -> None:
    pnl, pct = compute_trade_pnl(entry_price="100.00", current_price="90.00", quantity="2", side="SELL")
    assert pnl == Decimal("20.00")
    assert pct == Decimal("10.00")  # 20 / 200 * 100


def test_compute_trade_pnl_zero_cost_basis_percent_is_zero() -> None:
    pnl, pct = compute_trade_pnl(entry_price="0", current_price="10", quantity="0", side="BUY")
    assert pnl == Decimal("0.00")
    assert pct == Decimal("0.00")


def test_compute_max_drawdown_from_realized_pnls_usd_and_percent() -> None:
    # Equity curve (starting at 0): +10 => 10 (peak=10)
    # then -5 => 5 (dd=-5)
    # then -10 => -5 (dd=-15)  <-- max drawdown
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    series = [
        (t0, Decimal("10")),
        (t0 + timedelta(minutes=1), Decimal("-5")),
        (t0 + timedelta(minutes=2), Decimal("-10")),
    ]
    dd_usd, dd_pct = compute_max_drawdown_from_realized_pnls(series)
    assert dd_usd == Decimal("-15.00")
    assert dd_pct == Decimal("-150.00")  # -15 / peak(10) * 100


def test_compute_shadow_metrics_aggregates_realized_unrealized_win_rate_and_drawdown() -> None:
    now = datetime(2026, 1, 14, tzinfo=timezone.utc).isoformat()

    closed = [
        {"status": "CLOSED", "final_pnl": "10.00", "closed_at_iso": now},
        {"status": "CLOSED", "final_pnl": "-5.00", "closed_at_iso": now},
    ]
    open_ = [
        {"status": "OPEN", "symbol": "SPY", "side": "BUY", "entry_price": "100.00", "quantity": "2"},
    ]

    # Mark SPY at 110 -> unrealized +20
    metrics = compute_shadow_metrics(open_trades=open_, closed_trades=closed, live_prices_by_symbol={"SPY": "110.00"})

    assert metrics.closed_trades == 2
    assert metrics.open_trades == 1
    assert metrics.realized_pnl_usd == Decimal("5.00")  # 10 - 5
    assert metrics.unrealized_pnl_usd == Decimal("20.00")
    assert metrics.net_pnl_usd == Decimal("25.00")
    assert metrics.win_rate_percent == Decimal("50.00")  # 1/2 wins
    # Realized equity series: +10 then -5 => equity 10 then 5 => max_dd=-5, pct=-50%
    assert metrics.max_drawdown_usd == Decimal("-5.00")
    assert metrics.max_drawdown_percent == Decimal("-50.00")

