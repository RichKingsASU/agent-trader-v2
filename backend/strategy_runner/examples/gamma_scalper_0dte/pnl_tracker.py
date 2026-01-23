"""
PnL tracking for the 0DTE gamma scalper's SPY hedge trades.

Constraints:
- In-memory only (no persistence)
- Shadow-safe (no external side effects beyond logs; deterministic given inputs)
- Deterministic (no utc_now(); timestamp required for day-bucketing)

This module is intentionally standalone and does NOT modify execution/broker code.
It can be imported and invoked by the strategy runner / observers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Any, Dict, Optional

from backend.common.logging import log_event
from backend.time.nyse_time import parse_ts, to_nyse

logger = logging.getLogger(__name__)


def _to_decimal(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float, str)):
        # Cast through str for float safety and deterministic rounding behavior.
        return Decimal(str(v))
    return Decimal("0")


def _nyse_trading_day_from_ts(ts: str) -> date_type:
    """
    Deterministically map an ISO8601 timestamp to an America/New_York calendar date.
    """
    dt = parse_ts(ts)
    return to_nyse(dt).date()


class DailyReturnHardStop(RuntimeError):
    """
    Raised when the daily return hard stop threshold is reached.

    Callers may catch this to halt the strategy loop cleanly.
    """


@dataclass(frozen=True)
class PnlSnapshot:
    trading_day: Optional[date_type]
    symbol: str
    position_qty: Decimal
    avg_entry_price: Decimal
    mark_price: Optional[Decimal]
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    starting_equity: Optional[Decimal]
    daily_return_pct: Optional[Decimal]
    halted: bool
    halt_reason: Optional[str]


class PnLTracker:
    """
    Track realized/unrealized PnL for SPY hedge trades and compute daily return %.

    Accounting model: average-cost inventory for SPY shares (deterministic).

    Daily return definition:
      daily_return_pct = 100 * (realized_pnl + unrealized_pnl) / starting_equity
    """

    def __init__(
        self,
        *,
        symbol: str = "SPY",
        daily_return_hard_stop_pct: Decimal = Decimal("4.0"),
        emit_daily_return_every_update: bool = True,
    ) -> None:
        self._symbol = str(symbol)
        self._hard_stop_pct = _to_decimal(daily_return_hard_stop_pct)
        self._emit_daily_return_every_update = bool(emit_daily_return_every_update)

        # Day-scoped state.
        self._trading_day: Optional[date_type] = None
        self._starting_equity: Optional[Decimal] = None

        # Position + PnL state (SPY only).
        self._position_qty: Decimal = Decimal("0")  # signed shares
        self._avg_entry_price: Decimal = Decimal("0")  # average cost basis for open position
        self._mark_price: Optional[Decimal] = None
        self._realized_pnl: Decimal = Decimal("0")

        # Hard-stop latch.
        self._halted: bool = False
        self._halt_reason: Optional[str] = None

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def halted(self) -> bool:
        return self._halted

    def reset_day(self, *, ts: str, starting_equity: Decimal) -> None:
        """
        Start a new NYSE trading day.

        NOTE: This resets realized/unrealized PnL for the day, but does NOT assume
        positions are flat. If you carry a SPY position across days, unrealized
        PnL will naturally be computed from the carried cost basis and new mark.
        """
        self._trading_day = _nyse_trading_day_from_ts(ts)
        self._starting_equity = _to_decimal(starting_equity)
        self._realized_pnl = Decimal("0")
        self._halted = False
        self._halt_reason = None

        snap = self.snapshot()
        log_event(
            "pnl.daily_return",
            level="INFO",
            symbol=self._symbol,
            trading_day=self._trading_day.isoformat() if self._trading_day else None,
            starting_equity=str(self._starting_equity) if self._starting_equity is not None else None,
            daily_return_pct=str(snap.daily_return_pct) if snap.daily_return_pct is not None else None,
            realized_pnl=str(snap.realized_pnl),
            unrealized_pnl=str(snap.unrealized_pnl),
            total_pnl=str(snap.total_pnl),
            halted=snap.halted,
            halt_reason=snap.halt_reason,
        )

    def maybe_roll_day(self, *, ts: str, starting_equity: Optional[Decimal] = None) -> None:
        """
        Roll day if the NYSE trading day changed, deterministically based on ts.
        """
        td = _nyse_trading_day_from_ts(ts)
        if self._trading_day != td:
            # If caller provides starting equity, use it; otherwise keep last known.
            se = self._starting_equity if starting_equity is None else _to_decimal(starting_equity)
            if se is not None:
                self.reset_day(ts=ts, starting_equity=se)
            else:
                # No starting equity; still roll the day but daily return will be None.
                self._trading_day = td
                self._realized_pnl = Decimal("0")
                self._halted = False
                self._halt_reason = None

    def on_mark(self, *, ts: str, symbol: str, price: Any, event_id: Optional[str] = None) -> PnlSnapshot:
        """
        Update mark price (for unrealized PnL) for SPY.
        """
        if str(symbol) != self._symbol:
            return self.snapshot()

        self.maybe_roll_day(ts=ts)
        self._mark_price = _to_decimal(price)

        snap = self.snapshot()
        self._emit_update_log(ts=ts, event_id=event_id, snap=snap, update_type="mark")
        self._emit_daily_return_log_if_needed(ts=ts, event_id=event_id, snap=snap)
        self._enforce_hard_stop(ts=ts, event_id=event_id, snap=snap)
        return snap

    def on_fill(
        self,
        *,
        ts: str,
        symbol: str,
        side: str,
        qty: Any,
        price: Any,
        intent_id: Optional[str] = None,
        event_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PnlSnapshot:
        """
        Consume a SPY hedge fill.

        Args:
            ts: Fill timestamp (ISO8601). Required for deterministic day handling.
            symbol: Filled symbol. Only `self.symbol` is tracked.
            side: 'buy' or 'sell'
            qty: Filled quantity (shares)
            price: Fill price
            intent_id/event_id: optional identifiers for log correlation
            metadata: optional arbitrary fields (ignored for accounting)
        """
        if str(symbol) != self._symbol:
            return self.snapshot()

        self.maybe_roll_day(ts=ts)

        q = _to_decimal(qty)
        px = _to_decimal(price)
        if q <= Decimal("0") or px <= Decimal("0"):
            # Ignore invalid fills deterministically; still emit update log for observability.
            snap = self.snapshot()
            self._emit_update_log(
                ts=ts,
                event_id=event_id,
                snap=snap,
                update_type="fill_ignored",
                intent_id=intent_id,
                fill_side=str(side),
                fill_qty=str(q),
                fill_price=str(px),
            )
            return snap

        s = str(side).lower().strip()
        if s not in ("buy", "sell"):
            snap = self.snapshot()
            self._emit_update_log(
                ts=ts,
                event_id=event_id,
                snap=snap,
                update_type="fill_ignored",
                intent_id=intent_id,
                fill_side=str(side),
                fill_qty=str(q),
                fill_price=str(px),
            )
            return snap

        signed_qty = q if s == "buy" else -q
        self._apply_fill(signed_qty=signed_qty, price=px)

        snap = self.snapshot()
        self._emit_update_log(
            ts=ts,
            event_id=event_id,
            snap=snap,
            update_type="fill",
            intent_id=intent_id,
            fill_side=s,
            fill_qty=str(q),
            fill_price=str(px),
            fill_metadata=metadata,
        )
        self._emit_daily_return_log_if_needed(ts=ts, event_id=event_id, snap=snap)
        self._enforce_hard_stop(ts=ts, event_id=event_id, snap=snap)
        return snap

    def daily_return_pct(self) -> Optional[Decimal]:
        se = self._starting_equity
        if se is None or se <= Decimal("0"):
            return None
        total = self._realized_pnl + self._unrealized_pnl()
        return (total / se) * Decimal("100")

    def snapshot(self) -> PnlSnapshot:
        unreal = self._unrealized_pnl()
        total = self._realized_pnl + unreal
        dr = self.daily_return_pct()
        return PnlSnapshot(
            trading_day=self._trading_day,
            symbol=self._symbol,
            position_qty=self._position_qty,
            avg_entry_price=self._avg_entry_price,
            mark_price=self._mark_price,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=unreal,
            total_pnl=total,
            starting_equity=self._starting_equity,
            daily_return_pct=dr,
            halted=self._halted,
            halt_reason=self._halt_reason,
        )

    def assert_not_halted(self) -> None:
        """
        Deterministic hard-stop gate.
        """
        if self._halted:
            raise DailyReturnHardStop(self._halt_reason or "daily_return_hard_stop")

    def _unrealized_pnl(self) -> Decimal:
        if self._mark_price is None:
            return Decimal("0")
        if self._position_qty == Decimal("0"):
            return Decimal("0")
        # Works for both long (+qty) and short (-qty).
        return (self._mark_price - self._avg_entry_price) * self._position_qty

    def _apply_fill(self, *, signed_qty: Decimal, price: Decimal) -> None:
        """
        Apply a signed fill to average-cost inventory.
        """
        if signed_qty == Decimal("0"):
            return

        prev_qty = self._position_qty
        prev_avg = self._avg_entry_price

        # If no open position, this fill opens a new one.
        if prev_qty == Decimal("0"):
            self._position_qty = signed_qty
            self._avg_entry_price = price
            return

        # Same-direction add: update average price.
        if (prev_qty > 0 and signed_qty > 0) or (prev_qty < 0 and signed_qty < 0):
            new_qty = prev_qty + signed_qty
            # Weighted average cost basis.
            self._avg_entry_price = ((prev_avg * abs(prev_qty)) + (price * abs(signed_qty))) / abs(new_qty)
            self._position_qty = new_qty
            return

        # Opposite-direction trade: realize PnL on the closed portion.
        close_qty = min(abs(prev_qty), abs(signed_qty))
        close_qty_signed = Decimal("1") if prev_qty > 0 else Decimal("-1")
        # Realized PnL is (exit - entry) * shares_closed for long;
        # for short prev_qty < 0, this formula still works with close_qty_signed = -1.
        exit_price = price
        entry_price = prev_avg
        realized = (exit_price - entry_price) * (close_qty * close_qty_signed)
        self._realized_pnl += realized

        remaining_prev = prev_qty + (close_qty * (-close_qty_signed))  # after closing close_qty
        remaining_fill = signed_qty + (close_qty * close_qty_signed)  # remainder of incoming after closing

        # After netting, either we are flat, still same direction as prev, or flipped.
        new_qty = prev_qty + signed_qty
        self._position_qty = new_qty
        if new_qty == Decimal("0"):
            self._avg_entry_price = Decimal("0")
            return

        # If flipped direction, the remaining_fill opens a new position at 'price'.
        if remaining_prev == Decimal("0") and remaining_fill != Decimal("0"):
            self._avg_entry_price = price
            return

        # Otherwise, we reduced but didn't flip; avg stays.
        self._avg_entry_price = prev_avg

    def _emit_update_log(
        self,
        *,
        ts: str,
        event_id: Optional[str],
        snap: PnlSnapshot,
        update_type: str,
        intent_id: Optional[str] = None,
        fill_side: Optional[str] = None,
        fill_qty: Optional[str] = None,
        fill_price: Optional[str] = None,
        fill_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        log_event(
            "pnl.update",
            level="INFO",
            ts=ts,
            event_id=event_id,
            intent_id=intent_id,
            update_type=str(update_type),
            symbol=self._symbol,
            trading_day=snap.trading_day.isoformat() if snap.trading_day else None,
            starting_equity=str(snap.starting_equity) if snap.starting_equity is not None else None,
            position_qty=str(snap.position_qty),
            avg_entry_price=str(snap.avg_entry_price),
            mark_price=str(snap.mark_price) if snap.mark_price is not None else None,
            realized_pnl=str(snap.realized_pnl),
            unrealized_pnl=str(snap.unrealized_pnl),
            total_pnl=str(snap.total_pnl),
            daily_return_pct=str(snap.daily_return_pct) if snap.daily_return_pct is not None else None,
            halted=snap.halted,
            halt_reason=snap.halt_reason,
            fill_side=fill_side,
            fill_qty=fill_qty,
            fill_price=fill_price,
            fill_metadata=fill_metadata,
        )

    def _emit_daily_return_log_if_needed(self, *, ts: str, event_id: Optional[str], snap: PnlSnapshot) -> None:
        if not self._emit_daily_return_every_update:
            return
        log_event(
            "pnl.daily_return",
            level="INFO",
            ts=ts,
            event_id=event_id,
            symbol=self._symbol,
            trading_day=snap.trading_day.isoformat() if snap.trading_day else None,
            starting_equity=str(snap.starting_equity) if snap.starting_equity is not None else None,
            daily_return_pct=str(snap.daily_return_pct) if snap.daily_return_pct is not None else None,
            total_pnl=str(snap.total_pnl),
            realized_pnl=str(snap.realized_pnl),
            unrealized_pnl=str(snap.unrealized_pnl),
            hard_stop_pct=str(self._hard_stop_pct),
            halted=snap.halted,
            halt_reason=snap.halt_reason,
        )

    def _enforce_hard_stop(self, *, ts: str, event_id: Optional[str], snap: PnlSnapshot) -> None:
        if self._halted:
            return
        dr = snap.daily_return_pct
        if dr is None:
            return
        if dr >= self._hard_stop_pct:
            self._halted = True
            self._halt_reason = f"daily_return_pct>={self._hard_stop_pct}"
            # Emit once, at threshold crossing, with WARNING severity.
            log_event(
                "pnl.daily_return",
                level="WARNING",
                ts=ts,
                event_id=event_id,
                symbol=self._symbol,
                trading_day=snap.trading_day.isoformat() if snap.trading_day else None,
                starting_equity=str(snap.starting_equity) if snap.starting_equity is not None else None,
                daily_return_pct=str(dr),
                total_pnl=str(snap.total_pnl),
                realized_pnl=str(snap.realized_pnl),
                unrealized_pnl=str(snap.unrealized_pnl),
                hard_stop_pct=str(self._hard_stop_pct),
                halted=True,
                halt_reason=self._halt_reason,
            )
            raise DailyReturnHardStop(self._halt_reason)

