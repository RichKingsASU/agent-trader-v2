from __future__ import annotations

from datetime import datetime, timezone

from backend.ledger.models import LedgerTrade
from backend.marketplace.strategy_performance_snapshots import (
    build_monthly_strategy_performance_snapshots,
)


def _dt(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def test_build_monthly_strategy_performance_snapshots_doc_shape_and_id():
    trades = [
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
    ]

    out = build_monthly_strategy_performance_snapshots(
        trades,
        year=2025,
        month=12,
        mark_prices={"AAPL": 120.0},
    )

    assert "u1__s1__2025-12" in out
    snap = out["u1__s1__2025-12"]
    doc = snap.to_firestore_doc()

    assert doc["uid"] == "u1"
    assert doc["strategy_id"] == "s1"
    assert "period_start" in doc
    assert "period_end" in doc
    assert doc["realized_pnl"] == 100.0
    assert isinstance(doc["unrealized_pnl"], float)

