from __future__ import annotations

import json
import os
import sys

# Allow running as: `python3 scripts/ledger_pnl_demo.py` from repo root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.ledger.pnl import compute_pnl_fifo
from backend.ledger.sample_dataset import EXPECTED_TOTALS, SAMPLE_LEDGER_TRADES


def main() -> None:
    res = compute_pnl_fifo(SAMPLE_LEDGER_TRADES, trade_id_field="trade_id", sort_by_ts=True)
    print("Computed FIFO P&L:")
    print(
        json.dumps(
            {
                "realized_pnl_gross": res.realized_pnl_gross,
                "realized_fees": res.realized_fees,
                "realized_pnl_net": res.realized_pnl_net,
                "position_qty": res.position_qty,
                "open_long_lots": res.open_long_lots,
                "open_short_lots": res.open_short_lots,
            },
            default=str,
            indent=2,
            sort_keys=True,
        )
    )
    print("\nExpected totals:")
    print(json.dumps(EXPECTED_TOTALS, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

