"""
Trade Analytics Engine

Aggregates ledger trades to compute Daily P&L, Win/Loss ratios, and other performance metrics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from backend.ledger.models import LedgerTrade
from backend.ledger.pnl import compute_pnl_fifo
from backend.time.nyse_time import to_utc


@dataclass(frozen=True)
class DailyPnLSummary:
    """Daily P&L summary metrics"""
    
    date: str  # ISO date string (YYYY-MM-DD)
    total_pnl: float
    gross_pnl: float
    fees: float
    trades_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    symbols_traded: List[str]


@dataclass(frozen=True)
class TradeAnalytics:
    """Complete trade analytics summary"""
    
    daily_summaries: List[DailyPnLSummary]
    total_pnl: float
    total_trades: int
    overall_win_rate: float
    total_winning_trades: int
    total_losing_trades: int
    avg_daily_pnl: float
    best_day: Optional[DailyPnLSummary]
    worst_day: Optional[DailyPnLSummary]
    most_traded_symbols: List[tuple[str, int]]
    max_drawdown_pct: float


def _as_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC"""
    return to_utc(dt)


def _D(v: Any) -> Decimal:
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


def _to_fifo_trade_dict(t: LedgerTrade, *, i: int) -> Dict[str, Any]:
    """
    Convert a LedgerTrade into the dict-shape expected by compute_pnl_fifo().

    We include slippage in fees because compute_pnl_fifo treats `fees` as fee-like costs.
    """
    return {
        "trade_id": f"{t.ts.isoformat()}|{t.broker_fill_id or ''}|{t.order_id or ''}|{i}",
        "symbol": t.symbol,
        "side": t.side,
        "qty": float(t.qty),
        "price": float(t.price),
        "ts": t.ts,
        "fees": float((t.fees or 0.0) + (t.slippage or 0.0)),
    }


def _max_drawdown_pct_from_daily_pnl(
    daily_summaries: List[DailyPnLSummary],
    *,
    starting_equity: Decimal = Decimal("10000"),
) -> float:
    """
    Compute max drawdown % from a daily net P&L series.

    Drawdown is computed on an equity curve:
      equity_t = equity_{t-1} + daily_total_pnl
      dd_t = (HWM - equity_t) / HWM * 100
    """
    eq = _D(starting_equity)
    if eq <= 0:
        eq = Decimal("1")
    hwm = eq
    max_dd = Decimal("0")
    for d in daily_summaries:
        eq += _D(d.total_pnl)
        if eq > hwm:
            hwm = eq
        if hwm > 0:
            dd = (hwm - eq) / hwm * Decimal("100")
            if dd > max_dd:
                max_dd = dd
    return float(max_dd)


def compute_daily_pnl(
    trades: Iterable[LedgerTrade],
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[DailyPnLSummary]:
    """
    Compute daily P&L summaries from ledger trades using FIFO methodology.
    
    Args:
        trades: Iterable of LedgerTrade objects
        start_date: Optional start date filter (inclusive)
        end_date: Optional end date filter (exclusive)
        
    Returns:
        List of DailyPnLSummary objects, one per trading day
    """
    # Group trades by date
    trades_by_date: Dict[str, List[LedgerTrade]] = defaultdict(list)
    
    for trade in trades:
        trade_date = _as_utc(trade.ts).date()
        
        # Apply date filters
        if start_date and trade_date < start_date.date():
            continue
        if end_date and trade_date >= end_date.date():
            continue
            
        date_str = trade_date.isoformat()
        trades_by_date[date_str].append(trade)
    
    # Compute P&L for each day
    daily_summaries = []
    
    for date_str in sorted(trades_by_date.keys()):
        day_trades = trades_by_date[date_str]
        
        # Group trades by symbol for FIFO calculation
        trades_by_symbol: Dict[str, List[LedgerTrade]] = defaultdict(list)
        for t in day_trades:
            trades_by_symbol[t.symbol].append(t)
        
        # Calculate P&L using FIFO for each symbol
        daily_pnl = 0.0
        daily_fees = 0.0
        winning_trades = 0
        losing_trades = 0
        wins: List[float] = []
        losses: List[float] = []
        symbols_traded = list(trades_by_symbol.keys())
        
        for symbol, symbol_trades in trades_by_symbol.items():
            # Sort for deterministic trade_id generation
            symbol_trades.sort(key=lambda t: t.ts)

            fifo_trades = [_to_fifo_trade_dict(t, i=i) for i, t in enumerate(symbol_trades)]
            pnl_result = compute_pnl_fifo(fifo_trades, trade_id_field="trade_id", sort_by_ts=True)

            for closed in pnl_result.closed_positions:
                realized_pnl = float(closed.realized_pnl)
                fees = float(closed.total_fees)

                daily_pnl += realized_pnl
                daily_fees += fees

                if realized_pnl > 0:
                    winning_trades += 1
                    wins.append(realized_pnl)
                elif realized_pnl < 0:
                    losing_trades += 1
                    losses.append(realized_pnl)
        
        # Calculate summary statistics
        total_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        largest_win = max(wins) if wins else 0.0
        largest_loss = min(losses) if losses else 0.0
        
        daily_summaries.append(
            DailyPnLSummary(
                date=date_str,
                total_pnl=daily_pnl - daily_fees,
                gross_pnl=daily_pnl,
                fees=daily_fees,
                trades_count=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
                largest_win=largest_win,
                largest_loss=largest_loss,
                symbols_traded=symbols_traded,
            )
        )
    
    return daily_summaries


def compute_trade_analytics(
    trades: Iterable[LedgerTrade],
    *,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> TradeAnalytics:
    """
    Compute comprehensive trade analytics including daily summaries and aggregate metrics.
    
    Args:
        trades: Iterable of LedgerTrade objects
        start_date: Optional start date filter (inclusive)
        end_date: Optional end date filter (exclusive)
        
    Returns:
        TradeAnalytics object with complete performance summary
    """
    daily_summaries = compute_daily_pnl(trades, start_date=start_date, end_date=end_date)
    
    if not daily_summaries:
        return TradeAnalytics(
            daily_summaries=[],
            total_pnl=0.0,
            total_trades=0,
            overall_win_rate=0.0,
            total_winning_trades=0,
            total_losing_trades=0,
            avg_daily_pnl=0.0,
            best_day=None,
            worst_day=None,
            most_traded_symbols=[],
            max_drawdown_pct=0.0,
        )
    
    # Aggregate metrics
    total_pnl = sum(day.total_pnl for day in daily_summaries)
    total_trades = sum(day.trades_count for day in daily_summaries)
    total_winning = sum(day.winning_trades for day in daily_summaries)
    total_losing = sum(day.losing_trades for day in daily_summaries)
    overall_win_rate = (total_winning / total_trades * 100) if total_trades > 0 else 0.0
    avg_daily_pnl = total_pnl / len(daily_summaries) if daily_summaries else 0.0
    
    # Best and worst days
    best_day = max(daily_summaries, key=lambda d: d.total_pnl)
    worst_day = min(daily_summaries, key=lambda d: d.total_pnl)
    
    # Most traded symbols
    symbol_counts: Dict[str, int] = defaultdict(int)
    for day in daily_summaries:
        for symbol in day.symbols_traded:
            symbol_counts[symbol] += 1
    
    most_traded = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    max_drawdown_pct = _max_drawdown_pct_from_daily_pnl(daily_summaries)

    return TradeAnalytics(
        daily_summaries=daily_summaries,
        total_pnl=total_pnl,
        total_trades=total_trades,
        overall_win_rate=overall_win_rate,
        total_winning_trades=total_winning,
        total_losing_trades=total_losing,
        avg_daily_pnl=avg_daily_pnl,
        best_day=best_day,
        worst_day=worst_day,
        most_traded_symbols=most_traded,
        max_drawdown_pct=max_drawdown_pct,
    )


def compute_win_loss_ratio(
    trades: Iterable[LedgerTrade],
) -> Dict[str, Any]:
    """
    Compute win/loss ratio and related metrics.
    
    Args:
        trades: Iterable of LedgerTrade objects
        
    Returns:
        Dictionary containing win/loss metrics
    """
    trades_list = list(trades)
    
    if not trades_list:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "win_loss_ratio": 0.0,
        }
    
    # Group by symbol for FIFO calculation
    trades_by_symbol: Dict[str, List[LedgerTrade]] = defaultdict(list)
    for t in trades_list:
        trades_by_symbol[t.symbol].append(t)
    
    winning_trades = 0
    losing_trades = 0
    
    for symbol, symbol_trades in trades_by_symbol.items():
        symbol_trades.sort(key=lambda t: t.ts)
        fifo_trades = [_to_fifo_trade_dict(t, i=i) for i, t in enumerate(symbol_trades)]
        pnl_result = compute_pnl_fifo(fifo_trades, trade_id_field="trade_id", sort_by_ts=True)
        
        for closed_position in pnl_result.closed_positions:
            if float(closed_position.realized_pnl) > 0:
                winning_trades += 1
            elif float(closed_position.realized_pnl) < 0:
                losing_trades += 1
    
    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    loss_rate = (losing_trades / total_trades * 100) if total_trades > 0 else 0.0
    win_loss_ratio = (winning_trades / losing_trades) if losing_trades > 0 else float('inf')
    
    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "win_loss_ratio": win_loss_ratio,
    }
