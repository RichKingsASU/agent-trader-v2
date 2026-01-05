from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Tuple

from .models import LedgerTrade
from .pnl import aggregate_pnl, compute_fifo_pnl, compute_pnl_fifo


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class StrategyPeriodPnl:
    """
    Strategy P&L attribution for a period.

    Conventions:
    - realized_pnl: realized P&L generated *during* [period_start, period_end), net of fees/slippage
    - unrealized_pnl: unrealized P&L *as of* period_end, net of fees/slippage allocated into cost basis

    Marketplace fee linkage:
    - realized_pnl_gross: realized P&L before fees/slippage
    - realized_fees: fees+slippage realized during the period (FIFO allocated)
    """

    realized_pnl: float
    unrealized_pnl: float
    realized_pnl_gross: float
    realized_fees: float


def _trade_sort_key(t: LedgerTrade) -> tuple:
    # Deterministic ordering: (timestamp, broker_fill_id, order_id).
    return (
        t.ts,
        "" if t.broker_fill_id is None else str(t.broker_fill_id),
        "" if t.order_id is None else str(t.order_id),
    )


def _filter_as_of(
    trades: Iterable[LedgerTrade],
    *,
    as_of: datetime,
    as_of_inclusive: bool,
) -> list[LedgerTrade]:
    """
    Filter trades by as_of cutoff using the same convention as compute_fifo_pnl:
    - inclusive: keep trades with ts <= as_of
    - exclusive: keep trades with ts < as_of
    """
    out: list[LedgerTrade] = []
    for t in trades:
        if as_of_inclusive:
            if t.ts > as_of:
                continue
        else:
            if t.ts >= as_of:
                continue
        out.append(t)
    return out


def _realized_totals_as_of(
    trades: Iterable[LedgerTrade],
    *,
    as_of: datetime,
    as_of_inclusive: bool,
) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """
    Compute cumulative realized P&L totals (gross, fees, net) grouped by (tenant_id, uid, strategy_id)
    as of a timestamp cutoff.
    """
    filtered = _filter_as_of(trades, as_of=as_of, as_of_inclusive=as_of_inclusive)
    groups: Dict[Tuple[str, str, str], list[dict[str, Any]]] = {}
    for i, t in enumerate(sorted(filtered, key=_trade_sort_key)):
        k = (t.tenant_id, t.uid, t.strategy_id)
        groups.setdefault(k, []).append(
            {
                # Provide a deterministic id for stable FIFO ordering in ties.
                "trade_id": f"{t.ts.isoformat()}|{t.broker_fill_id or ''}|{t.order_id or ''}|{i}",
                "symbol": t.symbol,
                "side": t.side,
                "qty": float(t.qty),
                "price": float(t.price),
                "ts": t.ts,
                # Treat slippage as fee-like cost for fee attribution.
                "fees": float(t.fees or 0.0) + float(t.slippage or 0.0),
            }
        )

    out: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for k, group_trades in groups.items():
        res = compute_pnl_fifo(group_trades, trade_id_field="trade_id", sort_by_ts=True)
        out[k] = {
            "realized_pnl_gross": float(res.realized_pnl_gross),
            "realized_fees": float(res.realized_fees),
            "realized_pnl_net": float(res.realized_pnl_net),
        }
    return out


def compute_strategy_pnl_for_period(
    trades: Iterable[LedgerTrade],
    *,
    period_start: datetime,
    period_end: datetime,
    mark_prices: Mapping[str, float],
) -> Dict[Tuple[str, str, str], StrategyPeriodPnl]:
    """
    Compute P&L attribution by (tenant_id, uid, strategy_id) for a time window.

    Important: realized_pnl is computed as a *delta* of cumulative realized P&L:
      realized_in_period = realized(as_of=period_end) - realized(as_of=period_start)

    This ensures fills that open positions before the period (and close during the period)
    are attributed correctly.
    """
    start_utc = _as_utc(period_start)
    end_utc = _as_utc(period_end)
    if end_utc <= start_utc:
        raise ValueError("period_end must be > period_start")

    # Baseline at the start of the period (exclude trades at exactly period_start).
    rows_start = compute_fifo_pnl(
        trades=trades,
        mark_prices={},
        as_of=start_utc,
        as_of_inclusive=False,
    )
    agg_start = aggregate_pnl(rows_start)

    # End-of-period state (exclude trades at exactly period_end; treat period as [start, end)).
    rows_end = compute_fifo_pnl(
        trades=trades,
        mark_prices=mark_prices,
        as_of=end_utc,
        as_of_inclusive=False,
    )
    agg_end = aggregate_pnl(rows_end)

    # Fee-aware realized attribution (gross + fees via FIFO allocation).
    totals_start = _realized_totals_as_of(trades, as_of=start_utc, as_of_inclusive=False)
    totals_end = _realized_totals_as_of(trades, as_of=end_utc, as_of_inclusive=False)

    keys = set(agg_start.keys()) | set(agg_end.keys())
    keys |= set(totals_start.keys()) | set(totals_end.keys())
    out: Dict[Tuple[str, str, str], StrategyPeriodPnl] = {}
    for k in keys:
        realized_start = float(agg_start.get(k, {}).get("realized_pnl", 0.0))
        realized_end = float(agg_end.get(k, {}).get("realized_pnl", 0.0))
        unreal_end = float(agg_end.get(k, {}).get("unrealized_pnl", 0.0))

        gross_start = float(totals_start.get(k, {}).get("realized_pnl_gross", 0.0))
        gross_end = float(totals_end.get(k, {}).get("realized_pnl_gross", 0.0))
        fees_start = float(totals_start.get(k, {}).get("realized_fees", 0.0))
        fees_end = float(totals_end.get(k, {}).get("realized_fees", 0.0))
        realized_gross_in_period = gross_end - gross_start
        realized_fees_in_period = fees_end - fees_start

        # Prefer fee-aware realized net for the period; fall back to existing delta if absent.
        net_start = float(totals_start.get(k, {}).get("realized_pnl_net", realized_start))
        net_end = float(totals_end.get(k, {}).get("realized_pnl_net", realized_end))
        realized_net_in_period = net_end - net_start

        out[k] = StrategyPeriodPnl(
            realized_pnl=realized_net_in_period,
            unrealized_pnl=unreal_end,
            realized_pnl_gross=realized_gross_in_period,
            realized_fees=realized_fees_in_period,
        )
    return out

