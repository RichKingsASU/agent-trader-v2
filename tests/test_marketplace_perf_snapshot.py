from __future__ import annotations

from datetime import datetime, timezone

from backend.marketplace.performance import (
    aggregate_ledger_trades_for_period,
    compute_revenue_share_fee,
    month_period_utc,
)


def test_month_period_utc_december_rollover():
    start, end = month_period_utc(year=2025, month=12)
    assert start == datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_aggregate_ledger_trades_for_period_filters_and_sums():
    start = datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    trades = [
        {
            "closed_at": datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            "realized_pnl": 100.0,
            "fees": 3.0,
        },
        {
            "closed_at": datetime(2025, 12, 20, 12, 0, 0, tzinfo=timezone.utc),
            "realized_pnl": -50.0,
            "fees": 2.0,
        },
        # Outside the period
        {
            "closed_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "realized_pnl": 999.0,
            "fees": 999.0,
        },
    ]

    agg = aggregate_ledger_trades_for_period(trades, period_start=start, period_end=end)
    assert agg.trade_count == 2
    assert agg.realized_pnl == 50.0
    assert agg.fees == 5.0
    assert agg.net_profit == 45.0


def test_compute_revenue_share_fee_default_basis_positive_net_profit():
    term = {"revenue_share_bps": 2000}  # 20%
    fee = compute_revenue_share_fee(term=term, net_profit=-10.0)
    assert fee == 0.0

    fee2 = compute_revenue_share_fee(term=term, net_profit=100.0)
    assert fee2 == 20.0

