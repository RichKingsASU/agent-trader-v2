from __future__ import annotations

"""
P&L attribution over an immutable trade ledger.

Choice: FIFO (first-in-first-out).

Why FIFO:
- Deterministic realized P&L attribution at the *fill* level.
- Works for both long and short inventory when trades cross through zero.

Fee handling:
- Each ledger trade has `fees` as a positive USD cost for that fill.
- We allocate fees pro-rata by quantity:
  - Opening fees are carried with the opened lot as `fees_per_unit`.
  - Closing fees are charged on the closing trade per unit.
  - Realized net P&L for a matched quantity is:
      realized_gross - (open_fees_per_unit + close_fees_per_unit) * matched_qty
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Iterable, Mapping, Optional
from collections import deque

from backend.time.nyse_time import to_utc
from decimal import Decimal


def _as_utc(dt: datetime) -> datetime:
    return to_utc(dt)


def _D(v: Any) -> Decimal:
    """
    Convert a numeric-ish value to Decimal safely.

    IMPORTANT:
    - Never call Decimal(float) directly (binary float artifacts).
    - Use Decimal(str(x)) for int/float inputs.
    """
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        return Decimal(s) if s else Decimal("0")
    return Decimal(str(v))


@dataclass(slots=True)
class _Lot:
    qty: Decimal
    price: Decimal
    fees_per_unit: Decimal
    ts: datetime
    trade_id: str


@dataclass(frozen=True, slots=True)
class AttributedTrade:
    trade_id: str
    symbol: str
    side: str
    qty: float
    price: float
    ts: datetime
    fees: float
    realized_pnl_gross: float
    realized_fees: float
    realized_pnl_net: float
    position_qty_after: float


@dataclass(frozen=True, slots=True)
class ClosedPosition:
    """
    A "closed position event" attributable to a fill that closes inventory.

    One event per fill that produces non-zero realized attribution (P&L and/or fees).
    This is used by analytics to compute win rate and daily realized aggregation.
    """

    trade_id: str
    symbol: str
    side: str
    qty_closed: float
    realized_pnl: float  # gross realized P&L (before fees)
    total_fees: float  # allocated realized fees for the closed qty
    realized_pnl_net: float
    ts: datetime


@dataclass(frozen=True, slots=True)
class PnlResult:
    trades: list[AttributedTrade]
    closed_positions: list[ClosedPosition]
    realized_pnl_gross: float
    realized_fees: float
    realized_pnl_net: float
    position_qty: float
    open_long_lots: list[dict[str, Any]]
    open_short_lots: list[dict[str, Any]]


def _req_str(t: Mapping[str, Any], k: str) -> str:
    v = t.get(k)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"trade[{k}] is required")
    return v.strip()


def _req_num_pos(t: Mapping[str, Any], k: str) -> float:
    v = t.get(k)
    if not isinstance(v, (int, float)) or float(v) <= 0:
        raise ValueError(f"trade[{k}] must be a positive number")
    return float(v)


def _req_num_nonneg(t: Mapping[str, Any], k: str) -> float:
    v = t.get(k, 0.0)
    if not isinstance(v, (int, float)) or float(v) < 0:
        raise ValueError(f"trade[{k}] must be a non-negative number")
    return float(v)


def _req_ts(t: Mapping[str, Any], k: str = "ts") -> datetime:
    v = t.get(k)
    if not isinstance(v, datetime):
        raise ValueError(f"trade[{k}] must be a datetime")
    return _as_utc(v)


def compute_pnl_fifo(
    trades: Iterable[Mapping[str, Any]],
    *,
    trade_id_field: str = "trade_id",
    sort_by_ts: bool = True,
) -> PnlResult:
    """
    Compute realized P&L (gross + net of fees) using FIFO lot matching.

    Expected trade fields (minimum):
    - symbol: string
    - side: "buy" | "sell"
    - qty: number (>0)
    - price: number (>0)
    - ts: datetime
    - fees: number (>=0)

    trade_id is optional in the dict; if absent, it is synthesized as "t_{i}".
    """
    raw: list[dict[str, Any]] = [dict(t) for t in trades]
    if sort_by_ts:
        # Stable ordering: (ts, trade_id-or-index)
        def _key(i: int) -> tuple[datetime, str]:
            t = raw[i]
            ts = _req_ts(t)
            tid = t.get(trade_id_field)
            if isinstance(tid, str) and tid:
                return (ts, tid)
            return (ts, f"__idx_{i}")

        raw = [raw[i] for i in sorted(range(len(raw)), key=_key)]

    longs: Deque[_Lot] = deque()
    shorts: Deque[_Lot] = deque()
    position_qty = Decimal("0")

    realized_gross_total = Decimal("0")
    realized_fees_total = Decimal("0")
    out: list[AttributedTrade] = []

    for i, t in enumerate(raw):
        symbol = _req_str(t, "symbol").upper()
        side = _req_str(t, "side").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("trade[side] must be 'buy' or 'sell'")

        qty = _D(_req_num_pos(t, "qty"))
        price = _D(_req_num_pos(t, "price"))
        ts = _req_ts(t, "ts")
        fees = _D(_req_num_nonneg(t, "fees"))

        trade_id = t.get(trade_id_field)
        if not isinstance(trade_id, str) or not trade_id.strip():
            trade_id = f"t_{i}"
        trade_id = trade_id.strip()

        fees_per_unit = (fees / qty) if qty != 0 else Decimal("0")
        realized_gross = Decimal("0")
        realized_fees = Decimal("0")

        remaining = qty
        if side == "buy":
            # Close shorts first (buy-to-cover), then open/extend long inventory.
            while remaining > 0 and shorts:
                lot = shorts[0]
                match = min(remaining, lot.qty)
                realized_gross += (lot.price - price) * match
                realized_fees += (lot.fees_per_unit + fees_per_unit) * match
                lot.qty -= match
                remaining -= match
                if lot.qty <= 0:
                    shorts.popleft()

            if remaining > 0:
                longs.append(
                    _Lot(qty=remaining, price=price, fees_per_unit=fees_per_unit, ts=ts, trade_id=trade_id)
                )

            position_qty += qty

        else:  # sell
            # Close longs first (sell-to-close), then open/extend short inventory.
            while remaining > 0 and longs:
                lot = longs[0]
                match = min(remaining, lot.qty)
                realized_gross += (price - lot.price) * match
                realized_fees += (lot.fees_per_unit + fees_per_unit) * match
                lot.qty -= match
                remaining -= match
                if lot.qty <= 0:
                    longs.popleft()

            if remaining > 0:
                shorts.append(
                    _Lot(qty=remaining, price=price, fees_per_unit=fees_per_unit, ts=ts, trade_id=trade_id)
                )

            position_qty -= qty

        realized_net = realized_gross - realized_fees
        realized_gross_total += realized_gross
        realized_fees_total += realized_fees

        out.append(
            AttributedTrade(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                qty=float(qty),
                price=float(price),
                ts=ts,
                fees=float(fees),
                realized_pnl_gross=float(realized_gross),
                realized_fees=float(realized_fees),
                realized_pnl_net=float(realized_net),
                position_qty_after=float(position_qty),
            )
        )

    def _lot_to_dict(l: _Lot) -> dict[str, Any]:
        return {
            "qty": float(l.qty),
            "price": float(l.price),
            "fees_per_unit": float(l.fees_per_unit),
            "ts": l.ts,
            "trade_id": l.trade_id,
        }

    closed_positions: list[ClosedPosition] = []
    for t in out:
        if abs(float(t.realized_pnl_gross)) > 0.0 or abs(float(t.realized_fees)) > 0.0:
            closed_positions.append(
                ClosedPosition(
                    trade_id=t.trade_id,
                    symbol=t.symbol,
                    side=t.side,
                    qty_closed=t.qty,
                    realized_pnl=t.realized_pnl_gross,
                    total_fees=t.realized_fees,
                    realized_pnl_net=t.realized_pnl_net,
                    ts=t.ts,
                )
            )

    return PnlResult(
        trades=out,
        closed_positions=closed_positions,
        realized_pnl_gross=float(realized_gross_total),
        realized_fees=float(realized_fees_total),
        realized_pnl_net=float(realized_gross_total - realized_fees_total),
        position_qty=float(position_qty),
        open_long_lots=[_lot_to_dict(l) for l in list(longs)],
        open_short_lots=[_lot_to_dict(l) for l in list(shorts)],
    )

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .models import LedgerTrade


@dataclass(slots=True)
class Lot:
    qty: Decimal
    price: Decimal  # effective price including fees/slippage allocation (USD/share)


@dataclass(frozen=True, slots=True)
class SymbolPnl:
    tenant_id: str
    uid: str
    strategy_id: str
    symbol: str

    position_qty: float
    realized_pnl: float
    unrealized_pnl: float


def _trade_sort_key(t: LedgerTrade) -> Tuple:
    # Deterministic ordering: (timestamp, broker_fill_id, order_id).
    # Firestore timestamps can collide at ms resolution; we want stable FIFO behavior.
    return (
        t.ts,
        "" if t.broker_fill_id is None else str(t.broker_fill_id),
        "" if t.order_id is None else str(t.order_id),
    )


def _effective_price_per_unit(trade: LedgerTrade) -> float:
    """
    Distribute fees+slippage across quantity as a per-unit price adjustment.

    Convention:
    - BUY: costs increase effective price: px_eff = px + cost/qty
    - SELL: proceeds decrease effective price: px_eff = px - cost/qty
    """
    cost = _D(trade.fees or 0.0) + _D(trade.slippage or 0.0)
    qty = _D(trade.qty)
    per_unit = (cost / qty) if qty != 0 else Decimal("0")
    px = _D(trade.price)
    if trade.side == "buy":
        return float(px + per_unit)
    return float(px - per_unit)


def compute_fifo_pnl(
    *,
    trades: Iterable[LedgerTrade],
    mark_prices: Mapping[str, float],
    as_of: Optional[datetime] = None,
    as_of_inclusive: bool = True,
) -> List[SymbolPnl]:
    """
    Compute realized + unrealized P&L using FIFO lots per (tenant_id, uid, strategy_id, symbol).

    Inputs:
    - trades: fill-level ledger entries (append-only). You can pass multiple tenants; results are grouped.
    - mark_prices: {SYMBOL -> mark_price}. Symbols absent from marks get unrealized_pnl=0.
    - as_of: optional timestamp cutoff.
      - if as_of_inclusive=True (default): trades with ts > as_of are ignored (ts == as_of is included)
      - if as_of_inclusive=False: trades with ts >= as_of are ignored (ts == as_of is excluded)

    Output:
    - list of SymbolPnl entries (one per group)
    """
    groups: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}

    filtered: List[LedgerTrade] = []
    for t in trades:
        if as_of is not None:
            if as_of_inclusive:
                if t.ts > as_of:
                    continue
            else:
                if t.ts >= as_of:
                    continue
        filtered.append(t)

    for t in sorted(filtered, key=_trade_sort_key):
        key = (t.tenant_id, t.uid, t.strategy_id, t.symbol)
        if key not in groups:
            groups[key] = {"long": [], "short": [], "realized": Decimal("0")}

        state = groups[key]
        long_lots: List[Lot] = state["long"]  # type: ignore[assignment]
        short_lots: List[Lot] = state["short"]  # type: ignore[assignment]
        realized: Decimal = state["realized"]  # type: ignore[assignment]

        qty = _D(t.qty)
        px_eff = _D(_effective_price_per_unit(t))

        if t.side == "buy":
            qty_to_buy = qty

            # Cover shorts first (FIFO).
            while qty_to_buy > 0 and short_lots:
                lot = short_lots[0]
                cover = min(qty_to_buy, lot.qty)
                realized += (lot.price - px_eff) * cover
                lot.qty -= cover
                qty_to_buy -= cover
                if lot.qty <= 0:
                    short_lots.pop(0)

            # Remaining becomes new long lot.
            if qty_to_buy > 0:
                long_lots.append(Lot(qty=qty_to_buy, price=px_eff))

        else:  # sell
            qty_to_sell = qty

            # Close longs first (FIFO).
            while qty_to_sell > 0 and long_lots:
                lot = long_lots[0]
                close = min(qty_to_sell, lot.qty)
                realized += (px_eff - lot.price) * close
                lot.qty -= close
                qty_to_sell -= close
                if lot.qty <= 0:
                    long_lots.pop(0)

            # Remaining becomes new short lot.
            if qty_to_sell > 0:
                short_lots.append(Lot(qty=qty_to_sell, price=px_eff))

        state["realized"] = realized

    out: List[SymbolPnl] = []
    for (tenant_id, uid, strategy_id, symbol), state in groups.items():
        long_lots = state["long"]  # type: ignore[assignment]
        short_lots = state["short"]  # type: ignore[assignment]
        realized = _D(state["realized"])  # type: ignore[arg-type]

        mark = mark_prices.get(symbol)
        unreal = Decimal("0")
        if isinstance(mark, (int, float)):
            m = _D(mark)
            unreal += sum((m - lot.price) * lot.qty for lot in long_lots)
            unreal += sum((lot.price - m) * lot.qty for lot in short_lots)

        position_qty = sum(lot.qty for lot in long_lots) - sum(lot.qty for lot in short_lots)
        out.append(
            SymbolPnl(
                tenant_id=tenant_id,
                uid=uid,
                strategy_id=strategy_id,
                symbol=symbol,
                position_qty=float(position_qty),
                realized_pnl=float(realized),
                unrealized_pnl=float(unreal),
            )
        )

    # Deterministic output ordering for tests and downstream consumers.
    out.sort(key=lambda r: (r.tenant_id, r.uid, r.strategy_id, r.symbol))
    return out


def aggregate_pnl(
    symbol_rows: Iterable[SymbolPnl],
) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """
    Aggregate per-symbol P&L into (tenant_id, uid, strategy_id) totals.
    """
    agg: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for r in symbol_rows:
        k = (r.tenant_id, r.uid, r.strategy_id)
        if k not in agg:
            agg[k] = {"realized_pnl": 0.0, "unrealized_pnl": 0.0, "net_pnl": 0.0}
        agg[k]["realized_pnl"] += float(r.realized_pnl)
        agg[k]["unrealized_pnl"] += float(r.unrealized_pnl)
        agg[k]["net_pnl"] = agg[k]["realized_pnl"] + agg[k]["unrealized_pnl"]
    return agg

