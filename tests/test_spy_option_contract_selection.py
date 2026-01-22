from __future__ import annotations

from datetime import date

from backend.marketdata.options.contract_selection import OptionContract, OptionSnapshotView
from backend.marketdata.options.contract_selection import _liquidity_sort_key, _selection_key  # type: ignore


def _view(
    sym: str,
    *,
    bid: float,
    ask: float,
    bid_size: float = 1.0,
    ask_size: float = 1.0,
    volume: float = 0.0,
    open_interest: float = 0.0,
) -> OptionSnapshotView:
    return OptionSnapshotView(
        contract_symbol=sym,
        snapshot_time="2026-01-22T15:00:00Z",
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        last=None,
        volume=volume,
        open_interest=open_interest,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
    )


def test_liquidity_prefers_tighter_spread_pct() -> None:
    v_wide = _view("C1", bid=1.00, ask=1.20)  # spread_pct ~= 0.1818
    v_tight = _view("C2", bid=1.00, ask=1.02)  # spread_pct ~= 0.0198
    assert _liquidity_sort_key(v_tight) < _liquidity_sort_key(v_wide)


def test_liquidity_tie_breaks_by_deeper_quotes_then_vol_then_oi() -> None:
    # Same spread
    v1 = _view("C1", bid=1.00, ask=1.10, bid_size=1, ask_size=1, volume=10, open_interest=100)
    v2 = _view("C2", bid=1.00, ask=1.10, bid_size=5, ask_size=5, volume=0, open_interest=0)
    assert _liquidity_sort_key(v2) < _liquidity_sort_key(v1)

    # Same spread + depth, but higher volume wins
    v3 = _view("C3", bid=1.00, ask=1.10, bid_size=5, ask_size=5, volume=50, open_interest=0)
    assert _liquidity_sort_key(v3) < _liquidity_sort_key(v2)

    # Same spread + depth + volume, but higher OI wins
    v4 = _view("C4", bid=1.00, ask=1.10, bid_size=5, ask_size=5, volume=50, open_interest=10)
    assert _liquidity_sort_key(v4) < _liquidity_sort_key(v3)


def test_selection_prefers_0dte_then_nearest_atm_then_liquidity() -> None:
    today = date(2026, 1, 22)
    underlying = 500.0

    c_1dte_more_liquid = OptionContract(symbol="SPY1DTE", expiration=date(2026, 1, 23), right="call", strike=500.0)
    v_1dte_more_liquid = _view("SPY1DTE", bid=2.00, ask=2.01, bid_size=50, ask_size=50, volume=1000, open_interest=10000)

    c_0dte_less_liquid = OptionContract(symbol="SPY0DTE", expiration=date(2026, 1, 22), right="call", strike=500.0)
    v_0dte_less_liquid = _view("SPY0DTE", bid=2.00, ask=2.50, bid_size=1, ask_size=1, volume=1, open_interest=1)

    candidates = [
        (c_1dte_more_liquid, v_1dte_more_liquid),
        (c_0dte_less_liquid, v_0dte_less_liquid),
    ]
    best = sorted(
        candidates,
        key=lambda cv: _selection_key(contract=cv[0], view=cv[1], underlying_price=underlying, today_ny=today),
    )[0][0]
    assert best.symbol == "SPY0DTE"

    # Nearest ATM beats liquidity when DTE is equal.
    c_atm_bad = OptionContract(symbol="ATM_BAD", expiration=date(2026, 1, 22), right="call", strike=500.0)
    v_atm_bad = _view("ATM_BAD", bid=1.00, ask=1.50)
    c_1off_good = OptionContract(symbol="ONE_OFF_GOOD", expiration=date(2026, 1, 22), right="call", strike=501.0)
    v_1off_good = _view("ONE_OFF_GOOD", bid=1.00, ask=1.01, bid_size=100, ask_size=100)

    best2 = sorted(
        [(c_atm_bad, v_atm_bad), (c_1off_good, v_1off_good)],
        key=lambda cv: _selection_key(contract=cv[0], view=cv[1], underlying_price=underlying, today_ny=today),
    )[0][0]
    assert best2.symbol == "ATM_BAD"

    # If DTE + ATM distance tie, liquidity wins.
    c_tie1 = OptionContract(symbol="TIE1", expiration=date(2026, 1, 22), right="call", strike=500.0)
    v_tie1 = _view("TIE1", bid=1.00, ask=1.20)
    c_tie2 = OptionContract(symbol="TIE2", expiration=date(2026, 1, 22), right="call", strike=500.0)
    v_tie2 = _view("TIE2", bid=1.00, ask=1.02)
    best3 = sorted(
        [(c_tie1, v_tie1), (c_tie2, v_tie2)],
        key=lambda cv: _selection_key(contract=cv[0], view=cv[1], underlying_price=underlying, today_ny=today),
    )[0][0]
    assert best3.symbol == "TIE2"

