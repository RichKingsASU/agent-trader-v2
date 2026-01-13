from __future__ import annotations

import pytest

from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager
from backend.execution.order_lifecycle import (
    OrderLifecycleState,
    OrderLifecycleTracker,
    missing_required_edges,
)


def test_order_lifecycle_required_edges_present_across_examples():
    """
    Validate the canonical transition set supports the required spec edges:
      NEW -> ACCEPTED -> (FILLED|CANCELLED|EXPIRED)

    We simulate each edge on distinct order ids so the "missing" computation
    represents transition coverage, not a single order path.
    """
    tr = OrderLifecycleTracker()

    # NEW -> ACCEPTED
    tr.start_new(broker_order_id="o_new")
    tr.apply(broker_order_id="o_new", nxt=OrderLifecycleState.ACCEPTED)

    # ACCEPTED -> FILLED
    tr.start_new(broker_order_id="o_fill")
    tr.apply(broker_order_id="o_fill", nxt=OrderLifecycleState.ACCEPTED)
    tr.apply(broker_order_id="o_fill", nxt=OrderLifecycleState.FILLED)

    # ACCEPTED -> CANCELLED
    tr.start_new(broker_order_id="o_cancel")
    tr.apply(broker_order_id="o_cancel", nxt=OrderLifecycleState.ACCEPTED)
    tr.apply(broker_order_id="o_cancel", nxt=OrderLifecycleState.CANCELLED)

    # ACCEPTED -> EXPIRED
    tr.start_new(broker_order_id="o_expire")
    tr.apply(broker_order_id="o_expire", nxt=OrderLifecycleState.ACCEPTED)
    tr.apply(broker_order_id="o_expire", nxt=OrderLifecycleState.EXPIRED)

    assert missing_required_edges(observed=tr.transitions()) == set()


def test_order_lifecycle_rejects_invalid_transition_after_terminal():
    tr = OrderLifecycleTracker()
    tr.start_new(broker_order_id="o1")
    tr.apply(broker_order_id="o1", nxt=OrderLifecycleState.ACCEPTED)
    tr.apply(broker_order_id="o1", nxt=OrderLifecycleState.FILLED)

    with pytest.raises(Exception):
        tr.apply(broker_order_id="o1", nxt=OrderLifecycleState.ACCEPTED)


class _LedgerStub:
    def __init__(self):
        self.writes: list[dict] = []

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return 0

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        self.writes.append(
            {
                "broker_order_id": str((broker_order or {}).get("id") or ""),
                "qty": float((fill or {}).get("filled_qty") or 0.0),
                "cum_qty": float((fill or {}).get("cum_filled_qty") or 0.0),
            }
        )


class _BrokerStub:
    def place_order(self, *, intent):  # noqa: ARG002
        return {"id": "order_1", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


def test_engine_writes_incremental_fill_qty_for_cumulative_snapshots():
    ledger = _LedgerStub()
    risk = RiskManager(config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True), ledger=ledger)
    engine = ExecutionEngine(broker=_BrokerStub(), risk=risk, dry_run=True, ledger=ledger)

    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY240119C00450000",
        side="buy",
        qty=3,
        asset_class="OPTIONS",
        metadata={},
    )

    # First observation: cum=1 => delta=1
    o1 = {"id": "order_1", "status": "partially_filled", "filled_qty": "1", "filled_avg_price": "10", "filled_at": None}
    assert engine._write_ledger_fill(intent=intent, broker_order=o1, fill=o1) is not None

    # Duplicate observation: cum=1 => delta=0 (no write)
    o1_dup = {"id": "order_1", "status": "partially_filled", "filled_qty": "1", "filled_avg_price": "10", "filled_at": None}
    assert engine._write_ledger_fill(intent=intent, broker_order=o1_dup, fill=o1_dup) is None

    # Later observation: cum=3 => delta=2
    o1_later = {"id": "order_1", "status": "filled", "filled_qty": "3", "filled_avg_price": "10", "filled_at": None}
    assert engine._write_ledger_fill(intent=intent, broker_order=o1_later, fill=o1_later) is not None

    assert [w["qty"] for w in ledger.writes] == [1.0, 2.0]
    assert [w["cum_qty"] for w in ledger.writes] == [1.0, 3.0]

