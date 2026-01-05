from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Tuple


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC to avoid ambiguous math.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def month_period_utc(*, year: int, month: int) -> Tuple[datetime, datetime]:
    """
    Returns [period_start, period_end) in UTC for the given year/month.
    """
    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


@dataclass(frozen=True)
class PerfAggregation:
    trade_count: int
    realized_pnl: float
    fees: float
    net_profit: float


def aggregate_ledger_trades_for_period(
    trades: Iterable[Mapping[str, Any]],
    *,
    period_start: datetime,
    period_end: datetime,
    closed_at_field: str = "closed_at",
    realized_pnl_field: str = "realized_pnl",
    fees_field: str = "fees",
) -> PerfAggregation:
    """
    Aggregate ledger trades for a period, filtering by `closed_at` in [start, end).

    Assumptions for fee tracking:
    - `realized_pnl` is realized P&L BEFORE fees
    - `fees` is total fees paid (broker/clearing/etc.) for that realized P&L
    - `net_profit = realized_pnl - fees`
    """
    start_utc = _as_utc(period_start)
    end_utc = _as_utc(period_end)
    if end_utc <= start_utc:
        raise ValueError("period_end must be > period_start")

    trade_count = 0
    realized_pnl = 0.0
    fees = 0.0

    for t in trades:
        closed_at = t.get(closed_at_field)
        if closed_at is None:
            continue
        if not isinstance(closed_at, datetime):
            raise TypeError(f"{closed_at_field} must be a datetime, got {type(closed_at)}")
        closed_at_utc = _as_utc(closed_at)
        if closed_at_utc < start_utc or closed_at_utc >= end_utc:
            continue

        rp = t.get(realized_pnl_field, 0.0) or 0.0
        ff = t.get(fees_field, 0.0) or 0.0
        realized_pnl += float(rp)
        fees += float(ff)
        trade_count += 1

    net_profit = realized_pnl - fees
    return PerfAggregation(
        trade_count=trade_count,
        realized_pnl=realized_pnl,
        fees=fees,
        net_profit=net_profit,
    )


def compute_revenue_share_fee(
    *,
    term: Optional[Mapping[str, Any]],
    net_profit: float,
) -> Optional[float]:
    """
    Compute revenue share fee using a generic term shape.

    Term fields used (all optional):
    - revenue_share_bps: int (0..10000)
    - fee_basis: "net_profit_positive" | "net_profit" (default: net_profit_positive)

    Returns None if no term provided.
    """
    if term is None:
        return None

    basis_type = term.get("fee_basis", "net_profit_positive")
    if basis_type == "net_profit_positive":
        basis_amount = max(net_profit, 0.0)
    elif basis_type == "net_profit":
        basis_amount = net_profit
    else:
        raise ValueError(f"Unsupported fee_basis: {basis_type}")

    bps_raw = term.get("revenue_share_bps")
    if bps_raw is None:
        return None
    bps = int(bps_raw)
    if bps < 0 or bps > 10000:
        raise ValueError("revenue_share_bps must be 0..10000")

    return basis_amount * (bps / 10000.0)

