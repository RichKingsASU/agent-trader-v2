from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.ledger.models import LedgerTrade
from backend.ledger.pnl import aggregate_pnl, compute_fifo_pnl


def _dt(s: str) -> datetime:
    # ISO8601 with Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def test_fifo_pnl_attribution_deterministic_sample() -> None:
    trades = [
        # AAPL long build + partial sell
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=10,
            price=100.0,
            ts=_dt("2025-01-01T09:30:00Z"),
            order_id="ord-a1",
            broker_fill_id="fill-a1",
            fees=1.0,
            slippage=0.0,
        ),
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="buy",
            qty=5,
            price=110.0,
            ts=_dt("2025-01-01T09:31:00Z"),
            order_id="ord-a2",
            broker_fill_id="fill-a2",
            fees=0.5,
            slippage=0.0,
        ),
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="AAPL",
            side="sell",
            qty=8,
            price=120.0,
            ts=_dt("2025-01-01T09:35:00Z"),
            order_id="ord-a3",
            broker_fill_id="fill-a3",
            fees=0.8,
            slippage=0.0,
        ),
        # MSFT short then partial cover
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="MSFT",
            side="sell",
            qty=4,
            price=50.0,
            ts=_dt("2025-01-01T10:00:00Z"),
            order_id="ord-m1",
            broker_fill_id="fill-m1",
            fees=0.4,
            slippage=0.0,
        ),
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol="MSFT",
            side="buy",
            qty=1,
            price=40.0,
            ts=_dt("2025-01-01T10:05:00Z"),
            order_id="ord-m2",
            broker_fill_id="fill-m2",
            fees=0.1,
            slippage=0.0,
        ),
        # Different strategy for attribution sanity
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s2",
            run_id="r2",
            symbol="AAPL",
            side="buy",
            qty=1,
            price=200.0,
            ts=_dt("2025-01-01T11:00:00Z"),
            order_id="ord-s2-1",
            broker_fill_id="fill-s2-1",
            fees=0.0,
            slippage=0.0,
        ),
    ]

    marks = {"AAPL": 125.0, "MSFT": 45.0}
    rows = compute_fifo_pnl(trades=trades, mark_prices=marks)

    by_key = {(r.tenant_id, r.uid, r.strategy_id, r.symbol): r for r in rows}

    aapl_s1 = by_key[("t1", "u1", "s1", "AAPL")]
    assert aapl_s1.position_qty == pytest.approx(7.0)
    assert aapl_s1.realized_pnl == pytest.approx(158.4)
    assert aapl_s1.unrealized_pnl == pytest.approx(124.3)

    msft_s1 = by_key[("t1", "u1", "s1", "MSFT")]
    assert msft_s1.position_qty == pytest.approx(-3.0)
    assert msft_s1.realized_pnl == pytest.approx(9.8)
    assert msft_s1.unrealized_pnl == pytest.approx(14.7)

    aapl_s2 = by_key[("t1", "u1", "s2", "AAPL")]
    assert aapl_s2.position_qty == pytest.approx(1.0)
    assert aapl_s2.realized_pnl == pytest.approx(0.0)
    assert aapl_s2.unrealized_pnl == pytest.approx(-75.0)  # 125 - 200

    agg = aggregate_pnl(rows)
    s1_tot = agg[("t1", "u1", "s1")]
    assert s1_tot["realized_pnl"] == pytest.approx(168.2)  # 158.4 + 9.8
    assert s1_tot["unrealized_pnl"] == pytest.approx(139.0)  # 124.3 + 14.7
    assert s1_tot["net_pnl"] == pytest.approx(307.2)

