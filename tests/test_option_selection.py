from __future__ import annotations

from datetime import date

import pytest

from backend.trading.options.selection import OptionSelectionConfig, select_option_contract


def test_select_option_contract_nearest_exp_delta_band_closest_atm() -> None:
    as_of = date(2026, 1, 14)
    spot = 432.15

    contracts = [
        # Nearest exp: 2026-01-17
        {"option_symbol": "SPY260117C00430000", "expiration": "2026-01-17", "type": "call", "strike": 430, "greeks": {"delta": 0.58}},
        {"option_symbol": "SPY260117C00435000", "expiration": "2026-01-17", "type": "call", "strike": 435, "greeks": {"delta": 0.47}},
        {"option_symbol": "SPY260117C00440000", "expiration": "2026-01-17", "type": "call", "strike": 440, "greeks": {"delta": 0.38}},
        # Out of delta band (too low)
        {"option_symbol": "SPY260117C00445000", "expiration": "2026-01-17", "type": "call", "strike": 445, "greeks": {"delta": 0.22}},
        # Next exp: 2026-01-24 (ignored by expiration_rank=0)
        {"option_symbol": "SPY260124C00435000", "expiration": "2026-01-24", "type": "call", "strike": 435, "greeks": {"delta": 0.50}},
    ]

    cfg = OptionSelectionConfig(expiration_rank=0, delta_min=0.30, delta_max=0.60, right="CALL")
    chosen = select_option_contract(contracts=contracts, underlying_price=spot, cfg=cfg, as_of=as_of)

    # ATM selection: strikes 430 (|1.15|), 435 (|2.85|), 440 (|7.85|) -> choose 430
    assert chosen.contract_symbol == "SPY260117C00430000"
    assert chosen.expiration == date(2026, 1, 17)
    assert chosen.right == "CALL"
    assert chosen.strike == 430.0
    assert chosen.delta == pytest.approx(0.58)


def test_select_option_contract_tiebreaks_by_strike_then_symbol() -> None:
    as_of = date(2026, 1, 14)
    spot = 432.0

    # Two strikes equally distant from spot (431 and 433), both in band.
    # We choose lower strike (431). If same strike appears twice, choose lexicographically smallest symbol.
    contracts = [
        {"option_symbol": "AAA", "expiration": "2026-01-17", "type": "call", "strike": 431, "greeks": {"delta": 0.50}},
        {"option_symbol": "BBB", "expiration": "2026-01-17", "type": "call", "strike": 433, "greeks": {"delta": 0.50}},
        {"option_symbol": "ZZZ", "expiration": "2026-01-17", "type": "call", "strike": 431, "greeks": {"delta": 0.50}},
    ]

    cfg = OptionSelectionConfig(expiration_rank=0, delta_min=0.30, delta_max=0.60, right="CALL")
    chosen = select_option_contract(contracts=contracts, underlying_price=spot, cfg=cfg, as_of=as_of)

    assert chosen.strike == 431.0
    assert chosen.contract_symbol == "AAA"


def test_select_option_contract_raises_when_no_eligible() -> None:
    as_of = date(2026, 1, 14)
    spot = 432.15

    contracts = [
        {"option_symbol": "SPY260117C00435000", "expiration": "2026-01-17", "type": "call", "strike": 435, "greeks": {"delta": 0.10}},
    ]

    cfg = OptionSelectionConfig(expiration_rank=0, delta_min=0.30, delta_max=0.60, right="CALL")
    with pytest.raises(ValueError):
        select_option_contract(contracts=contracts, underlying_price=spot, cfg=cfg, as_of=as_of)

