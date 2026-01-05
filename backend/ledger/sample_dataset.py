from __future__ import annotations

from datetime import datetime, timezone

"""
Sample immutable ledger trades + expected P&L (FIFO).

All fields align to:
  tenants/{tid}/ledger_trades/{trade_id}

Required fields per spec:
- uid, strategy_id, run_id, symbol, side, qty, price, ts, fees
"""

TID = "t_demo"
UID = "uid_demo"
STRATEGY_ID = "strat_demo"
RUN_ID = "run_2025_12_29"
SYMBOL = "SPY"


def _ts(y: int, m: int, d: int, hh: int, mm: int, ss: int) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


SAMPLE_LEDGER_TRADES: list[dict] = [
    {
        "trade_id": "t1_buy_10_100",
        "tenant_id": TID,
        "uid": UID,
        "strategy_id": STRATEGY_ID,
        "run_id": RUN_ID,
        "symbol": SYMBOL,
        "side": "buy",
        "qty": 10.0,
        "price": 100.0,
        "ts": _ts(2025, 12, 29, 14, 0, 0),
        "fees": 1.0,
    },
    {
        "trade_id": "t2_buy_10_110",
        "tenant_id": TID,
        "uid": UID,
        "strategy_id": STRATEGY_ID,
        "run_id": RUN_ID,
        "symbol": SYMBOL,
        "side": "buy",
        "qty": 10.0,
        "price": 110.0,
        "ts": _ts(2025, 12, 29, 14, 1, 0),
        "fees": 1.0,
    },
    # Close 15 shares (FIFO): 10@100 + 5@110 at 120
    {
        "trade_id": "t3_sell_15_120",
        "tenant_id": TID,
        "uid": UID,
        "strategy_id": STRATEGY_ID,
        "run_id": RUN_ID,
        "symbol": SYMBOL,
        "side": "sell",
        "qty": 15.0,
        "price": 120.0,
        "ts": _ts(2025, 12, 29, 14, 2, 0),
        "fees": 1.5,
    },
    # Sell 10 shares: closes remaining 5@110 and opens short 5@90
    {
        "trade_id": "t4_sell_10_90",
        "tenant_id": TID,
        "uid": UID,
        "strategy_id": STRATEGY_ID,
        "run_id": RUN_ID,
        "symbol": SYMBOL,
        "side": "sell",
        "qty": 10.0,
        "price": 90.0,
        "ts": _ts(2025, 12, 29, 14, 3, 0),
        "fees": 1.0,
    },
    # Buy-to-cover 5 shares at 80
    {
        "trade_id": "t5_buy_5_80",
        "tenant_id": TID,
        "uid": UID,
        "strategy_id": STRATEGY_ID,
        "run_id": RUN_ID,
        "symbol": SYMBOL,
        "side": "buy",
        "qty": 5.0,
        "price": 80.0,
        "ts": _ts(2025, 12, 29, 14, 4, 0),
        "fees": 1.0,
    },
]


# Expected totals (FIFO):
# - Gross realized:
#   t3: (120-100)*10 + (120-110)*5 = 250
#   t4 close long: (90-110)*5 = -100
#   t5 close short: (90-80)*5 = 50
#   total gross = 200
#
# - Total fees paid = 1 + 1 + 1.5 + 1 + 1 = 5.5
# - End position = 0, so all fees are realized
# - Net realized = 200 - 5.5 = 194.5
EXPECTED_TOTALS = {
    "realized_pnl_gross": 200.0,
    "realized_fees": 5.5,
    "realized_pnl_net": 194.5,
    "position_qty": 0.0,
}

