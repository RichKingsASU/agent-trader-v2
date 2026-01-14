"""
Deterministic example: choose an eligible SPY option contract.

Run:
  python scripts/example_option_selection_spy.py
"""

from __future__ import annotations

from datetime import date

from backend.trading.options.selection import OptionSelectionConfig, select_option_contract


def main() -> None:
    # Fixed inputs so the output is deterministic.
    symbol = "SPY"
    as_of = date(2026, 1, 14)
    spot = 432.15

    # Minimal, provider-agnostic "chain-like" payload.
    # Two expirations, multiple strikes/deltas. We want:
    # - nearest expiration (rank=0) => 2026-01-17
    # - delta band 0.30..0.60 (abs) => keep deltas within band
    # - closest ATM strike => strike closest to 432.15 among remaining
    contracts = [
        # Nearest exp: 2026-01-17
        {"option_symbol": "SPY260117C00430000", "expiration": "2026-01-17", "type": "call", "strike": 430, "greeks": {"delta": 0.58}},
        {"option_symbol": "SPY260117C00435000", "expiration": "2026-01-17", "type": "call", "strike": 435, "greeks": {"delta": 0.47}},
        {"option_symbol": "SPY260117C00440000", "expiration": "2026-01-17", "type": "call", "strike": 440, "greeks": {"delta": 0.38}},
        # Out of delta band (too low)
        {"option_symbol": "SPY260117C00445000", "expiration": "2026-01-17", "type": "call", "strike": 445, "greeks": {"delta": 0.22}},
        # Next exp: 2026-01-24 (should be ignored by expiration_rank=0)
        {"option_symbol": "SPY260124C00435000", "expiration": "2026-01-24", "type": "call", "strike": 435, "greeks": {"delta": 0.50}},
    ]

    cfg = OptionSelectionConfig(
        expiration_rank=0,
        delta_min=0.30,
        delta_max=0.60,
        use_abs_delta=True,
        right="CALL",
        min_dte=0,
        max_dte=None,
    )

    chosen = select_option_contract(contracts=contracts, underlying_price=spot, cfg=cfg, as_of=as_of)

    print(f"Underlying: {symbol} spot={spot} as_of={as_of.isoformat()}")
    print(
        "Chosen contract:",
        f"{chosen.contract_symbol} {chosen.right} exp={chosen.expiration.isoformat()} strike={chosen.strike} delta={chosen.delta}",
    )


if __name__ == "__main__":
    main()

