from backend.execution.fill_deltas import compute_delta_from_cumulative


def test_delta_fill_from_cumulative_first_fill():
    d = compute_delta_from_cumulative(cum_qty=2.0, cum_avg_price=10.0, prev_fills=[])
    assert d.delta_qty == 2.0
    assert d.delta_price == 10.0


def test_delta_fill_from_cumulative_second_fill_preserves_cum_avg():
    # First fill: 1 @ 10. Second fill makes cumulative 2 @ 11 => total notional 22.
    # Previously recorded: 1*10 = 10 notional; remaining delta notional = 12 for delta_qty=1 => delta_price=12.
    d = compute_delta_from_cumulative(cum_qty=2.0, cum_avg_price=11.0, prev_fills=[(1.0, 10.0)])
    assert d.delta_qty == 1.0
    assert d.delta_price == 12.0


def test_delta_fill_noop_when_already_recorded():
    d = compute_delta_from_cumulative(cum_qty=2.0, cum_avg_price=10.0, prev_fills=[(2.0, 10.0)])
    assert d.delta_qty == 0.0

