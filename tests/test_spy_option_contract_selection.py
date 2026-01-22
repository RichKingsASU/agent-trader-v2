from __future__ import annotations

from datetime import date

import pytest

from backend.marketdata.options.contract_selection import select_scalper_contract_from_data
from backend.marketdata.options.models import OptionContract


def _snap(*, bid: float, ask: float, bs: float = 10, a_s: float = 10, volume: float = 0, oi: float = 0):
    # Mimic Alpaca-ish "latestQuote" shape
    return {
        "latestQuote": {"bp": bid, "ap": ask, "bs": bs, "as": a_s, "t": "2026-01-22T14:30:00Z"},
        "volume": volume,
        "open_interest": oi,
    }


def test_selects_nearest_atm_then_tightest_spread():
    today = date(2026, 1, 22)
    underlying_price = 481.50

    # Equidistant strikes: 481 and 482 (distance 0.5). Liquidity should decide.
    contracts = [
        OptionContract(symbol="SPY251022C00481000", underlying_symbol="SPY", expiration_date=today, strike=481.0, right="call"),
        OptionContract(symbol="SPY251022C00482000", underlying_symbol="SPY", expiration_date=today, strike=482.0, right="call"),
        # Non-ATM should be ignored
        OptionContract(symbol="SPY251022C00480000", underlying_symbol="SPY", expiration_date=today, strike=480.0, right="call"),
    ]
    snapshots = {
        # Wider spread
        "SPY251022C00481000": _snap(bid=2.00, ask=2.20, volume=100, oi=500),
        # Tighter spread => should win
        "SPY251022C00482000": _snap(bid=2.05, ask=2.10, volume=10, oi=10),
        "SPY251022C00480000": _snap(bid=2.50, ask=2.60, volume=1000, oi=2000),
    }

    sel = select_scalper_contract_from_data(
        underlying_symbol="SPY",
        right="call",
        today=today,
        underlying_price=underlying_price,
        contracts=contracts,
        snapshots_by_symbol=snapshots,
        dte_max=1,
    )
    assert sel.contract_symbol == "SPY251022C00482000"
    assert sel.dte == 0


def test_prefers_higher_size_then_volume_then_open_interest_when_spread_ties():
    today = date(2026, 1, 22)
    underlying_price = 500.00
    contracts = [
        OptionContract(symbol="A", underlying_symbol="SPY", expiration_date=today, strike=500.0, right="put"),
        OptionContract(symbol="B", underlying_symbol="SPY", expiration_date=today, strike=500.0, right="put"),
        OptionContract(symbol="C", underlying_symbol="SPY", expiration_date=today, strike=500.0, right="put"),
    ]
    # Same spread for all; use sizes/volume/oi tie-breakers
    snapshots = {
        "A": _snap(bid=1.00, ask=1.10, bs=1, a_s=1, volume=100, oi=1000),
        # Bigger displayed size wins (bs+as)
        "B": _snap(bid=1.00, ask=1.10, bs=50, a_s=50, volume=1, oi=1),
        # Big volume but smaller size => should lose to B under our ordering
        "C": _snap(bid=1.00, ask=1.10, bs=10, a_s=10, volume=10000, oi=5000),
    }
    sel = select_scalper_contract_from_data(
        underlying_symbol="SPY",
        right="put",
        today=today,
        underlying_price=underlying_price,
        contracts=contracts,
        snapshots_by_symbol=snapshots,
        dte_max=1,
    )
    assert sel.contract_symbol == "B"


def test_prefers_0dte_over_1dte_as_final_tiebreaker():
    today = date(2026, 1, 22)
    tomorrow = date(2026, 1, 23)
    underlying_price = 480.00
    contracts = [
        OptionContract(symbol="D0", underlying_symbol="SPY", expiration_date=today, strike=480.0, right="call"),
        OptionContract(symbol="D1", underlying_symbol="SPY", expiration_date=tomorrow, strike=480.0, right="call"),
    ]
    snapshots = {
        "D0": _snap(bid=1.00, ask=1.10, bs=10, a_s=10, volume=10, oi=10),
        "D1": _snap(bid=1.00, ask=1.10, bs=10, a_s=10, volume=10, oi=10),
    }
    sel = select_scalper_contract_from_data(
        underlying_symbol="SPY",
        right="call",
        today=today,
        underlying_price=underlying_price,
        contracts=contracts,
        snapshots_by_symbol=snapshots,
        dte_max=1,
    )
    assert sel.contract_symbol == "D0"
    assert sel.dte == 0


def test_raises_when_no_eligible_contracts():
    today = date(2026, 1, 22)
    with pytest.raises(RuntimeError):
        select_scalper_contract_from_data(
            underlying_symbol="SPY",
            right="call",
            today=today,
            underlying_price=500.0,
            contracts=[],
            snapshots_by_symbol={},
            dte_max=1,
        )

