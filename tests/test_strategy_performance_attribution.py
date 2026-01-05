from __future__ import annotations

from datetime import datetime, timezone

from backend.ledger.models import LedgerTrade
from backend.ledger.pnl import compute_fifo_pnl
from backend.ledger.strategy_performance import compute_strategy_pnl_for_period
from backend.marketplace.performance import month_period_utc


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def test_compute_fifo_pnl_as_of_inclusive_flag():
    trades = [
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=1,
            price=100.0,
            ts=_dt(2025, 12, 1, 0, 0, 0),
        )
    ]

    rows_inclusive = compute_fifo_pnl(trades=trades, mark_prices={"AAPL": 100.0}, as_of=_dt(2025, 12, 1, 0, 0, 0))
    assert len(rows_inclusive) == 1
    assert rows_inclusive[0].position_qty == 1.0

    rows_exclusive = compute_fifo_pnl(
        trades=trades,
        mark_prices={"AAPL": 100.0},
        as_of=_dt(2025, 12, 1, 0, 0, 0),
        as_of_inclusive=False,
    )
    assert rows_exclusive == []


def test_compute_strategy_pnl_for_period_realized_delta_and_unrealized_mark_to_market():
    # Month: 2025-12
    period_start, period_end = month_period_utc(year=2025, month=12)

    trades = [
        # Open before the month.
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=10,
            price=100.0,
            ts=_dt(2025, 11, 30, 23, 0, 0),
        ),
        # Close at exactly period_start -> should be attributed to the month.
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="sell",
            qty=10,
            price=110.0,
            ts=_dt(2025, 12, 1, 0, 0, 0),
        ),
        # New open inside the month; remains open at period_end.
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=1,
            price=100.0,
            ts=_dt(2025, 12, 15, 0, 0, 0),
        ),
    ]

    out = compute_strategy_pnl_for_period(
        trades,
        period_start=period_start,
        period_end=period_end,
        mark_prices={"AAPL": 120.0},
    )

    k = ("t1", "u1", "s1")
    assert k in out
    # 10 shares closed at 110 with cost basis 100 => +100
    assert out[k].realized_pnl == 100.0
    # 1 share open with mark 120 vs basis 100 => +20
    assert out[k].unrealized_pnl == 20.0


def test_compute_strategy_pnl_for_period_includes_realized_fees_and_gross_pnl() -> None:
    period_start, period_end = month_period_utc(year=2025, month=12)

    trades = [
        # Open before the month with an opening fee.
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=1,
            price=100.0,
            ts=_dt(2025, 11, 30, 23, 0, 0),
            fees=1.0,
        ),
        # Close inside the month with a closing fee.
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="sell",
            qty=1,
            price=110.0,
            ts=_dt(2025, 12, 10, 12, 0, 0),
            fees=2.0,
        ),
    ]

    out = compute_strategy_pnl_for_period(
        trades,
        period_start=period_start,
        period_end=period_end,
        mark_prices={},
    )

    k = ("t1", "u1", "s1")
    assert k in out
    # Gross realized P&L: +10
    assert out[k].realized_pnl_gross == 10.0
    # Realized fees: open fee (1) + close fee (2) => 3
    assert out[k].realized_fees == 3.0
    # Net realized P&L: 10 - 3 => 7
    assert out[k].realized_pnl == 7.0

