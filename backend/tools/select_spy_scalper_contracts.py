"""
CLI: Deterministically choose SPY option contract(s) for scalper.

Output:
- JSON containing `contract_symbol` + `metadata`

Env required:
- APCA_API_KEY_ID
- APCA_API_SECRET_KEY
- APCA_API_BASE_URL (defaults to paper host in backend env helpers)

Optional:
- ALPACA_DATA_HOST
- ALPACA_STOCK_FEED (default: iex)
- ALPACA_OPTIONS_FEED (passed to snapshots endpoint when set)
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import timezone

from backend.marketdata.options.contract_selection import (
    select_spy_scalper_contract,
    select_spy_scalper_contracts,
)
from backend.time.nyse_time import utc_now


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Select SPY scalper option contract(s) via Alpaca snapshots.")
    p.add_argument("--right", choices=["call", "put", "both"], default="both", help="Select call/put/both.")
    p.add_argument("--dte-max", type=int, default=1, help="Max DTE (0..1 recommended).")
    p.add_argument(
        "--near-atm-strikes-per-exp",
        type=int,
        default=3,
        help="How many closest-to-ATM strikes to snapshot per expiration.",
    )
    p.add_argument("--options-feed", default=os.getenv("ALPACA_OPTIONS_FEED"), help="Alpaca options feed (e.g. indicative/opra).")
    p.add_argument("--stock-feed", default=os.getenv("ALPACA_STOCK_FEED", "iex"), help="Alpaca stock feed for SPY price (iex/sip).")
    return p.parse_args()


def main() -> int:
    a = _args()
    now = utc_now().astimezone(timezone.utc)

    if a.right == "both":
        out = select_spy_scalper_contracts(
            now_utc=now,
            dte_max=a.dte_max,
            near_atm_strikes_per_exp=a.near_atm_strikes_per_exp,
            options_feed=a.options_feed,
            stock_feed=a.stock_feed,
        )
    else:
        out = select_spy_scalper_contract(
            right=a.right,
            now_utc=now,
            dte_max=a.dte_max,
            near_atm_strikes_per_exp=a.near_atm_strikes_per_exp,
            options_feed=a.options_feed,
            stock_feed=a.stock_feed,
        )

    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

