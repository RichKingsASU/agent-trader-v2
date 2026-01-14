"""
Trade Analytics Engine

Aggregates ledger trades to compute Daily P&L, Win/Loss ratios, and other performance metrics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional

from backend.ledger.models import LedgerTrade
from backend.ledger.pnl import compute_pnl_fifo
from backend.time.nyse_time import to_utc


DEFAULT_FLAT_PNL_ABS: float = 1.0
DEFAULT_FLAT_PNL_FEE_MULTIPLIER: float = 0.25


def compute_expectancy(*, win_rate_pct: float, avg_win: float, avg_loss: float) -> float:
    """
    Compute expectancy (expected value per trade).

    Conventions:
    - win_rate_pct is 0..100
    - avg_win is >= 0 (mean of winning trade P&L)
    - avg_loss is <= 0 (mean of losing trade P&L)

    Expectancy = P(win) * avg_win + P(loss) * avg_loss
    """
    if win_rate_pct <= 0.0 and avg_win == 0.0 and avg_loss == 0.0:
        return 0.0
    p_win = max(0.0, min(1.0, float(win_rate_pct) / 100.0))
    p_loss = 1.0 - p_win
    return (p_win * float(avg_win)) + (p_loss * float(avg_loss))


def compute_flat_threshold(*, fees: float) -> float:
    """
    Compute the +/- band used to classify a day as Flat.

    Threshold logic:
    - flat_threshold = max(DEFAULT_FLAT_PNL_ABS, DEFAULT_FLAT_PNL_FEE_MULTIPLIER * abs(fees))
    """
    return max(DEFAULT_FLAT_PNL_ABS, DEFAULT_FLAT_PNL_FEE_MULTIPLIER * abs(float(fees)))


def classify_daily_summary(*, total_pnl: float, flat_threshold: float) -> str:
    """
    Classify daily performance into a human-readable label.

    - Profitable: total_pnl >  flat_threshold
    - Losing:     total_pnl < -flat_threshold
    - Flat:       otherwise
    """
    tp = float(total_pnl)
    th = float(flat_threshold)
    if tp > th:
        return "Profitable"
    if tp < -th:
        return "Losing"
    return "Flat"


def threshold_logic_text(*, flat_threshold: float) -> str:
    th = float(flat_threshold)
    return f"Profitable if total_pnl > {th:.2f}; Losing if total_pnl < -{th:.2f}; else Flat"


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
    expectancy: float
    performance_label: str
    flat_threshold: float
    threshold_logic: str
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
    overall_avg_win: float
    overall_avg_loss: float
    expectancy: float
    avg_daily_pnl: float
    best_day: Optional[DailyPnLSummary]
    worst_day: Optional[DailyPnLSummary]
    most_traded_symbols: List[tuple[str, int]]


def _as_utc(dt: datetime) -> datetime:
    """Convert datetime to UTC"""
    return to_utc(dt)


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
            # Sort by timestamp to ensure proper FIFO ordering
            symbol_trades.sort(key=lambda t: t.ts)
            
            # Use FIFO to calculate realized P&L for closed positions
            pnl_result = compute_pnl_fifo(symbol_trades)
            
            for closed_position in pnl_result.closed_positions:
                realized_pnl = float(closed_position.realized_pnl)
                fees = float(closed_position.total_fees)
                net_pnl = realized_pnl - fees
                
                daily_pnl += realized_pnl
                daily_fees += fees
                
                # Win/loss attribution uses NET P&L to match total_pnl.
                if net_pnl > 0:
                    winning_trades += 1
                    wins.append(net_pnl)
                elif net_pnl < 0:
                    losing_trades += 1
                    losses.append(net_pnl)
        
        # Calculate summary statistics
        total_trades = winning_trades + losing_trades
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        largest_win = max(wins) if wins else 0.0
        largest_loss = min(losses) if losses else 0.0

        net_total_pnl = daily_pnl - daily_fees
        expectancy = compute_expectancy(win_rate_pct=win_rate, avg_win=avg_win, avg_loss=avg_loss)
        flat_threshold = compute_flat_threshold(fees=daily_fees)
        performance_label = classify_daily_summary(total_pnl=net_total_pnl, flat_threshold=flat_threshold)
        
        daily_summaries.append(
            DailyPnLSummary(
                date=date_str,
                total_pnl=net_total_pnl,
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
                expectancy=expectancy,
                performance_label=performance_label,
                flat_threshold=flat_threshold,
                threshold_logic=threshold_logic_text(flat_threshold=flat_threshold),
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
            overall_avg_win=0.0,
            overall_avg_loss=0.0,
            expectancy=0.0,
            avg_daily_pnl=0.0,
            best_day=None,
            worst_day=None,
            most_traded_symbols=[],
        )
    
    # Aggregate metrics
    total_pnl = sum(day.total_pnl for day in daily_summaries)
    total_trades = sum(day.trades_count for day in daily_summaries)
    total_winning = sum(day.winning_trades for day in daily_summaries)
    total_losing = sum(day.losing_trades for day in daily_summaries)
    overall_win_rate = (total_winning / total_trades * 100) if total_trades > 0 else 0.0
    avg_daily_pnl = total_pnl / len(daily_summaries) if daily_summaries else 0.0

    overall_avg_win = (
        sum(day.avg_win * day.winning_trades for day in daily_summaries) / total_winning
        if total_winning > 0
        else 0.0
    )
    overall_avg_loss = (
        sum(day.avg_loss * day.losing_trades for day in daily_summaries) / total_losing
        if total_losing > 0
        else 0.0
    )
    expectancy = compute_expectancy(
        win_rate_pct=overall_win_rate, avg_win=overall_avg_win, avg_loss=overall_avg_loss
    )
    
    # Best and worst days
    best_day = max(daily_summaries, key=lambda d: d.total_pnl)
    worst_day = min(daily_summaries, key=lambda d: d.total_pnl)
    
    # Most traded symbols
    symbol_counts: Dict[str, int] = defaultdict(int)
    for day in daily_summaries:
        for symbol in day.symbols_traded:
            symbol_counts[symbol] += 1
    
    most_traded = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return TradeAnalytics(
        daily_summaries=daily_summaries,
        total_pnl=total_pnl,
        total_trades=total_trades,
        overall_win_rate=overall_win_rate,
        total_winning_trades=total_winning,
        total_losing_trades=total_losing,
        overall_avg_win=overall_avg_win,
        overall_avg_loss=overall_avg_loss,
        expectancy=expectancy,
        avg_daily_pnl=avg_daily_pnl,
        best_day=best_day,
        worst_day=worst_day,
        most_traded_symbols=most_traded,
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
        pnl_result = compute_pnl_fifo(symbol_trades)
        
        for closed_position in pnl_result.closed_positions:
            net_pnl = float(closed_position.realized_pnl) - float(closed_position.total_fees)
            if net_pnl > 0:
                winning_trades += 1
            elif net_pnl < 0:
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
