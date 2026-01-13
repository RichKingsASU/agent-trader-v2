from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from backend.ledger.models import LedgerTrade
from backend.ledger.pnl import compute_fifo_pnl, compute_pnl_fifo
from backend.ledger.options_attribution import GreeksSnapshot, attribute_option_mtm


def _dt(s: str) -> datetime:
    # ISO8601 with Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def test_options_multiplier_inferred_from_occ_symbol_realized() -> None:
    # 1 contract bought and later sold; prices are quoted per share premium.
    sym = "SPY251230C00500000"
    trades = [
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol=sym,
            side="buy",
            qty=1,
            price=1.00,
            ts=_dt("2025-12-30T14:00:00Z"),
            fees=1.00,
            slippage=0.0,
            # multiplier omitted on purpose; should infer 100
        ),
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol=sym,
            side="sell",
            qty=1,
            price=1.50,
            ts=_dt("2025-12-30T14:10:00Z"),
            fees=1.00,
            slippage=0.0,
        ),
    ]

    rows = compute_fifo_pnl(trades=trades, mark_prices={})
    row = rows[0]

    # Effective prices:
    # - buy eff = 1.00 + 1/(1*100) = 1.01
    # - sell eff = 1.50 - 1/(1*100) = 1.49
    # Realized = (1.49 - 1.01) * 1 * 100 = 48.0
    assert row.realized_pnl == pytest.approx(48.0)
    assert row.unrealized_pnl == pytest.approx(0.0)

    # Also validate the dict-based FIFO engine (realized-only) supports multiplier correctly.
    dict_trades = [
        {
            "trade_id": "t1",
            "symbol": sym,
            "side": "buy",
            "qty": 1,
            "price": 1.00,
            "ts": _dt("2025-12-30T14:00:00Z"),
            "fees": 1.00,
            "multiplier": 100.0,
        },
        {
            "trade_id": "t2",
            "symbol": sym,
            "side": "sell",
            "qty": 1,
            "price": 1.50,
            "ts": _dt("2025-12-30T14:10:00Z"),
            "fees": 1.00,
            "multiplier": 100.0,
        },
    ]
    res = compute_pnl_fifo(dict_trades, trade_id_field="trade_id", sort_by_ts=True)
    assert res.realized_pnl_net == pytest.approx(48.0)


def test_options_multiplier_applies_to_unrealized_mtm() -> None:
    sym = "SPY251230P00490000"
    trades = [
        LedgerTrade(
            tenant_id="t1",
            uid="u1",
            strategy_id="s1",
            run_id="r1",
            symbol=sym,
            side="buy",
            qty=2,
            price=1.00,
            ts=_dt("2025-12-30T14:00:00Z"),
            fees=0.0,
            slippage=0.0,
        ),
    ]

    rows = compute_fifo_pnl(trades=trades, mark_prices={sym: 1.20})
    row = rows[0]

    # Unrealized = (1.20 - 1.00) * 2 * 100 = 40.0
    assert row.position_qty == pytest.approx(2.0)
    assert row.realized_pnl == pytest.approx(0.0)
    assert row.unrealized_pnl == pytest.approx(40.0)


def test_greek_mtm_attribution_sums_with_residual() -> None:
    start = GreeksSnapshot(
        ts=_dt("2025-12-30T14:00:00Z"),
        option_price=2.50,
        underlying_price=495.50,
        iv=0.20,
        delta=0.65,
        gamma=0.05,
        vega=0.10,
        theta=-0.12,
    )
    end = GreeksSnapshot(
        ts=_dt("2025-12-30T15:00:00Z"),
        option_price=3.25,
        underlying_price=497.50,
        iv=0.205,
        delta=0.75,  # not used in attribution (start greeks used)
        gamma=0.07,
        vega=0.12,
        theta=-0.20,
    )

    out = attribute_option_mtm(start=start, end=end, qty=10, multiplier=100.0)

    # Total MTM from observed option price change:
    assert out.total_mtm_pnl == pytest.approx((3.25 - 2.50) * 10 * 100.0)

    # Sanity: components + residual reconstruct total.
    recon = out.delta_pnl + out.gamma_pnl + out.vega_pnl + out.theta_pnl + out.residual_pnl
    assert recon == pytest.approx(out.total_mtm_pnl)

