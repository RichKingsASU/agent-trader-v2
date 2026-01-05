from __future__ import annotations

from backend.ledger.pnl import compute_pnl_fifo
from backend.ledger.sample_dataset import EXPECTED_TOTALS, SAMPLE_LEDGER_TRADES


def test_compute_pnl_fifo_sample_dataset_totals() -> None:
    res = compute_pnl_fifo(SAMPLE_LEDGER_TRADES, trade_id_field="trade_id", sort_by_ts=True)
    assert res.position_qty == EXPECTED_TOTALS["position_qty"]
    assert round(res.realized_pnl_gross, 10) == EXPECTED_TOTALS["realized_pnl_gross"]
    assert round(res.realized_fees, 10) == EXPECTED_TOTALS["realized_fees"]
    assert round(res.realized_pnl_net, 10) == EXPECTED_TOTALS["realized_pnl_net"]


def test_compute_pnl_fifo_sample_dataset_per_trade_sanity() -> None:
    res = compute_pnl_fifo(SAMPLE_LEDGER_TRADES, trade_id_field="trade_id", sort_by_ts=True)
    by_id = {t.trade_id: t for t in res.trades}

    # Trade 3 closes 15 long shares with FIFO.
    assert round(by_id["t3_sell_15_120"].realized_pnl_gross, 10) == 250.0
    assert round(by_id["t3_sell_15_120"].realized_pnl_net, 10) == 247.0

    # Trade 4 crosses through zero: closes remaining 5 long at a loss and opens 5 short.
    assert round(by_id["t4_sell_10_90"].realized_pnl_gross, 10) == -100.0
    assert round(by_id["t4_sell_10_90"].realized_pnl_net, 10) == -101.0

    # Trade 5 buys to cover short at a profit.
    assert round(by_id["t5_buy_5_80"].realized_pnl_gross, 10) == 50.0
    assert round(by_id["t5_buy_5_80"].realized_pnl_net, 10) == 48.5

