from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from backend.time.nyse_time import to_utc


Side = Literal["buy", "sell"]


def _as_utc(dt: datetime) -> datetime:
    return to_utc(dt)


@dataclass(frozen=True, slots=True)
class LedgerTrade:
    """
    Immutable, append-only ledger entry representing a *fill* (or fill-equivalent).

    Firestore path:
      tenants/{tenant_id}/ledger_trades/{trade_id}

    Notes:
    - `fees` and `slippage` are modeled as positive USD amounts (costs).
    - `qty` is positive; direction is expressed via `side`.
    """

    tenant_id: str
    uid: str
    strategy_id: str
    run_id: str
    symbol: str

    side: Side
    qty: float
    price: float
    ts: datetime

    order_id: Optional[str] = None
    broker_fill_id: Optional[str] = None

    fees: float = 0.0
    slippage: float = 0.0

    account_id: Optional[str] = None
    asset_class: Optional[str] = None  # "EQUITY" | "OPTIONS" | "CRYPTO" | "FOREX" (best-effort)
    multiplier: float = 1.0  # e.g. 100 for US equity options; 1 for equities

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.uid:
            raise ValueError("uid is required")
        if not self.strategy_id:
            raise ValueError("strategy_id is required")
        if not self.run_id:
            raise ValueError("run_id is required")

        sym = (self.symbol or "").strip().upper()
        if not sym:
            raise ValueError("symbol is required")
        object.__setattr__(self, "symbol", sym)

        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if not (isinstance(self.qty, (int, float)) and self.qty > 0):
            raise ValueError("qty must be a positive number")
        if not (isinstance(self.price, (int, float)) and self.price > 0):
            raise ValueError("price must be a positive number")

        if self.fees < 0:
            raise ValueError("fees must be >= 0")
        if self.slippage < 0:
            raise ValueError("slippage must be >= 0")

        # Options P&L must be multiplied by contract size (usually 100).
        # We infer multiplier=100 when either:
        # - asset_class explicitly indicates OPTIONS, OR
        # - the symbol looks like an OCC-style contract symbol (e.g. SPY251230C00500000).
        mult = float(self.multiplier)
        if mult <= 0:
            raise ValueError("multiplier must be > 0")
        ac = (self.asset_class or "").strip().upper()
        sym_u = sym  # already normalized
        looks_like_occ = (
            len(sym_u) >= 15
            and any(c in sym_u for c in ("C", "P"))
            and sym_u[-9:-8] in ("C", "P")  # ...{C|P}{strike8}
            and sym_u[-8:].isdigit()
            and sym_u[-15:-9].isdigit()  # yymmdd
        )
        if mult == 1.0 and (ac == "OPTIONS" or looks_like_occ):
            mult = 100.0
            object.__setattr__(self, "multiplier", mult)

        object.__setattr__(self, "ts", _as_utc(self.ts))

