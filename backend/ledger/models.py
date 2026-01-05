from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional


Side = Literal["buy", "sell"]


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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

        object.__setattr__(self, "ts", _as_utc(self.ts))

