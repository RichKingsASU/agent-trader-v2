"""
Example: deterministic option selection for SPY.

This script is intentionally offline (no Alpaca credentials required). It uses a
small synthetic chain and demonstrates the standardized selection behavior:

- nearest expiration (rank configurable)
- delta band eligibility (abs(delta) in [0.30, 0.60])
- closest ATM strike within the chosen expiration
"""

from __future__ import annotations

from datetime import date

"""
When executed as a file path (python backend/tools/...py), Python sets sys.path[0]
to this folder, which prevents importing the top-level `backend` package.
Keep this example runnable in both modes by adding the repo root to sys.path.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.options.selection import (
    OptionCandidate,
    OptionSelectionConfig,
    select_option_contract,
)


def main() -> None:
    underlying = "SPY"
    underlying_price = 480.25

    chain = [
        # Nearest expiration (2026-01-16) - multiple strikes/deltas
        OptionCandidate(underlying, date(2026, 1, 16), "CALL", 475.0, 0.66, "SPY260116C00475000"),  # out of band
        OptionCandidate(underlying, date(2026, 1, 16), "CALL", 480.0, 0.52, "SPY260116C00480000"),  # best
        OptionCandidate(underlying, date(2026, 1, 16), "CALL", 481.0, 0.49, "SPY260116C00481000"),
        OptionCandidate(underlying, date(2026, 1, 16), "PUT",  480.0, -0.48, "SPY260116P00480000"),
        # Next expiration (2026-01-23)
        OptionCandidate(underlying, date(2026, 1, 23), "CALL", 480.0, 0.50, "SPY260123C00480000"),
    ]

    cfg = OptionSelectionConfig(
        expiration_rank=0,  # nearest expiry
        delta_min=0.30,
        delta_max=0.60,
        use_abs_delta=True,
        right="CALL",
    )

    chosen = select_option_contract(chain, underlying_price=underlying_price, cfg=cfg)

    print(
        "chosen_contract",
        {
            "underlying": chosen.underlying,
            "expiration": chosen.expiration.isoformat(),
            "right": chosen.right,
            "strike": chosen.strike,
            "delta": chosen.delta,
            "contract_symbol": chosen.contract_symbol,
        },
    )


if __name__ == "__main__":
    main()

