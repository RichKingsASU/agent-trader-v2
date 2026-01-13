#!/usr/bin/env python3
"""
CLI wrapper for the single-command backtest().

Example:
  python scripts/backtest.py --strategy GammaScalper --symbol SPY --start 2025-12-01 --end 2025-12-31
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True, help="Strategy name (e.g., GammaScalper)")
    p.add_argument("--symbol", required=True, help="Symbol (e.g., SPY)")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--capital", type=float, default=100000.0, help="Starting capital")
    p.add_argument("--slippage-bps", type=int, default=1, help="Slippage in basis points")
    p.add_argument("--regime", default=None, help="Optional regime (LONG_GAMMA/SHORT_GAMMA/NEUTRAL)")

    args = p.parse_args()

    functions_dir = Path(__file__).resolve().parent.parent / "functions"
    sys.path.insert(0, str(functions_dir))

    from backtest import backtest  # type: ignore

    if not os.getenv("APCA_API_KEY_ID") or not os.getenv("APCA_API_SECRET_KEY"):
        raise SystemExit("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY environment variables.")

    out = backtest(
        strategy=args.strategy,
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        start_capital=args.capital,
        slippage_bps=args.slippage_bps,
        regime=args.regime,
    )

    m = out["metrics"]
    print("Backtest complete")
    print(f"  strategy: {out['strategy']}")
    print(f"  symbol:   {out['symbol']}")
    print(f"  period:   {out['date_range']['start']} -> {out['date_range']['end']}")
    print("")
    print("Key metrics")
    print(f"  realized_pnl:   ${m['realized_pnl_dollars']:,.2f}")
    print(f"  unrealized_pnl: ${m['unrealized_pnl_dollars']:,.2f}")
    print(f"  max_drawdown:   {m['max_drawdown_pct']:.2f}%")
    print(f"  trade_count:    {m['total_trades']}")
    print("")
    print(f"Metrics artifact: {out['artifacts']['metrics_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

