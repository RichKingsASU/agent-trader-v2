from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float, str)):
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")
    return Decimal("0")


@dataclass(slots=True)
class PnlSnapshot:
    symbol: str
    position_qty: Decimal
    avg_entry_price: Decimal
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    net_pnl_usd: Decimal


class PnlTracker:
    """
    Minimal intent-level PnL tracker for a single symbol.

    Notes:
    - This intentionally treats emitted intents as executions at the provided mark price.
    - It is used for observability only; callers must ensure it never affects execution paths.
    """

    def __init__(self, *, symbol: str, pnl_target_usd: Optional[Decimal] = None) -> None:
        self.symbol = str(symbol).upper()
        self._qty = Decimal("0")  # signed
        self._avg_entry = Decimal("0")
        self._realized = Decimal("0")
        self._target = pnl_target_usd if isinstance(pnl_target_usd, Decimal) else None
        self._target_logged = False

    def reset(self) -> None:
        self._qty = Decimal("0")
        self._avg_entry = Decimal("0")
        self._realized = Decimal("0")
        self._target_logged = False

    def register_entry(self, *, signed_qty: Any, price: Any) -> None:
        q = _d(signed_qty)
        px = _d(price)
        if q == Decimal("0") or px <= Decimal("0"):
            return

        if self._qty == Decimal("0"):
            self._qty = q
            self._avg_entry = px
            return

        # Same direction: update VWAP.
        if (self._qty > 0 and q > 0) or (self._qty < 0 and q < 0):
            new_qty = self._qty + q
            if new_qty == Decimal("0"):
                self._qty = Decimal("0")
                self._avg_entry = Decimal("0")
                return
            w0 = abs(self._qty)
            w1 = abs(q)
            self._avg_entry = (self._avg_entry * w0 + px * w1) / abs(new_qty)
            self._qty = new_qty
            return

        # Opposite direction: observability-only simplification.
        # We do NOT realize here (exit realization is handled explicitly by the caller).
        self._qty = self._qty + q
        self._avg_entry = px if self._qty != Decimal("0") else Decimal("0")

    def realize_all(self, *, exit_price: Any) -> Decimal:
        px = _d(exit_price)
        if self._qty == Decimal("0") or px <= Decimal("0"):
            return Decimal("0")

        if self._qty > 0:
            pnl = (px - self._avg_entry) * self._qty
        else:
            pnl = (self._avg_entry - px) * abs(self._qty)

        self._realized += pnl
        self._qty = Decimal("0")
        self._avg_entry = Decimal("0")
        return pnl

    def snapshot(self, *, mark_price: Any) -> PnlSnapshot:
        px = _d(mark_price)
        unreal = Decimal("0")
        if self._qty != Decimal("0") and px > Decimal("0") and self._avg_entry > Decimal("0"):
            if self._qty > 0:
                unreal = (px - self._avg_entry) * self._qty
            else:
                unreal = (self._avg_entry - px) * abs(self._qty)
        net = self._realized + unreal
        return PnlSnapshot(
            symbol=self.symbol,
            position_qty=self._qty,
            avg_entry_price=self._avg_entry,
            realized_pnl_usd=self._realized,
            unrealized_pnl_usd=unreal,
            net_pnl_usd=net,
        )

    def should_log_target_reached(self, *, net_pnl_usd: Any) -> bool:
        if self._target is None or self._target <= Decimal("0"):
            return False
        if self._target_logged:
            return False
        net = _d(net_pnl_usd)
        if net >= self._target:
            self._target_logged = True
            return True
        return False

    def target_usd(self) -> Optional[Decimal]:
        return self._target

    def as_log_fields(self, *, mark_price: Any) -> Dict[str, Any]:
        snap = self.snapshot(mark_price=mark_price)
        return {
            "pnl_symbol": snap.symbol,
            "pnl_position_qty": str(snap.position_qty),
            "pnl_avg_entry_price": str(snap.avg_entry_price),
            "pnl_realized_usd": str(snap.realized_pnl_usd),
            "pnl_unrealized_usd": str(snap.unrealized_pnl_usd),
            "pnl_net_usd": str(snap.net_pnl_usd),
            "pnl_mark_price": str(_d(mark_price)) if _d(mark_price) > Decimal("0") else None,
            "pnl_target_usd": str(self._target) if isinstance(self._target, Decimal) else None,
        }

