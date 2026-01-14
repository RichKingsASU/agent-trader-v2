"""
Performance Interpretation (human-readable signals)

This module translates raw daily metrics (P&L, win rate, avg win/loss) into:
- Expectancy (edge) per trade
- Day classification: PROFITABLE / FLAT / LOSING
- A compact daily narrative summary

Notes on inputs:
- `DailyPnLSummary.total_pnl` is NET (gross realized P&L minus fees)
- `DailyPnLSummary.avg_win` / `avg_loss` are based on net realized P&L from FIFO closeouts
  (i.e., after allocated fees). Fees are also reported separately for transparency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

from backend.analytics.trade_parser import DailyPnLSummary


DayLabel = Literal["PROFITABLE", "FLAT", "LOSING"]


@dataclass(frozen=True)
class DailySummaryThresholds:
    """
    Thresholds for interpretation.

    flat_pnl_abs:
      Absolute net P&L (in account currency) below which the day is treated as FLAT.
      Example: 10.0 means -$10 to +$10 is considered FLAT.
    """

    flat_pnl_abs: float = 10.0


def compute_expectancy_per_trade(
    *,
    win_rate_pct: float,
    avg_win: float,
    avg_loss: float,
    avg_fee_per_trade: float = 0.0,
) -> Dict[str, float]:
    """
    Compute expectancy per trade (and an optional fee-adjusted variant).

    Definitions (per closed trade):
    - p_win = win_rate_pct / 100
    - p_loss = 1 - p_win
    - Expectancy (base) = p_win * avg_win + p_loss * avg_loss
    - Fee-adjusted expectancy = Expectancy (base) - avg_fee_per_trade

    Where `avg_loss` is expected to be negative (e.g., -12.34).
    """

    p_win = max(0.0, min(1.0, float(win_rate_pct) / 100.0))
    p_loss = 1.0 - p_win

    avg_fee = float(avg_fee_per_trade)
    expectancy_base = p_win * float(avg_win) + p_loss * float(avg_loss)
    expectancy_fee_adjusted = expectancy_base - avg_fee

    return {
        "p_win": p_win,
        "p_loss": p_loss,
        "avg_fee_per_trade": avg_fee,
        "expectancy_per_trade": expectancy_base,
        "expectancy_fee_adjusted_per_trade": expectancy_fee_adjusted,
    }


def classify_day(
    *,
    net_pnl: float,
    thresholds: DailySummaryThresholds = DailySummaryThresholds(),
) -> DayLabel:
    """
    Classify the trading day using explicit threshold logic:

    - FLAT if |net_pnl| <= flat_pnl_abs
    - PROFITABLE if net_pnl >  flat_pnl_abs
    - LOSING if net_pnl < -flat_pnl_abs
    """

    flat = float(thresholds.flat_pnl_abs)
    pnl = float(net_pnl)
    if abs(pnl) <= flat:
        return "FLAT"
    return "PROFITABLE" if pnl > 0 else "LOSING"


def emit_daily_summary(
    day: DailyPnLSummary,
    *,
    thresholds: DailySummaryThresholds = DailySummaryThresholds(),
    title: Optional[str] = None,
) -> Dict[str, object]:
    """
    Emit a daily performance summary.

    Returns a dict with:
    - label (PROFITABLE/FLAT/LOSING)
    - computed metrics (expectancy, avg win/loss, win rate)
    - human-readable summary text
    """

    trades = int(day.trades_count or 0)
    avg_fee = (float(day.fees) / trades) if trades > 0 else 0.0

    expectancy = compute_expectancy_per_trade(
        win_rate_pct=float(day.win_rate),
        avg_win=float(day.avg_win),
        avg_loss=float(day.avg_loss),
        # avg_win/avg_loss are already net-of-fees from FIFO attribution in trade_parser.
        # We still compute avg_fee_per_trade and include it in the output for transparency,
        # but we avoid subtracting it again from expectancy.
        avg_fee_per_trade=0.0,
    )

    label = classify_day(net_pnl=float(day.total_pnl), thresholds=thresholds)

    avg_loss_abs = abs(float(day.avg_loss)) if float(day.avg_loss) != 0 else 0.0
    win_loss_ratio = (float(day.avg_win) / avg_loss_abs) if avg_loss_abs > 0 else float("inf")

    edge = float(expectancy["expectancy_per_trade"])
    edge_signal = "positive edge" if edge > 0 else ("break-even edge" if edge == 0 else "negative edge")

    # Interpretation heuristics: keep short and actionable.
    if trades == 0:
        key_signal = "No closed trades today; not enough data to infer edge."
    else:
        if edge > 0 and float(day.total_pnl) > 0:
            key_signal = "You had positive expectancy and converted it into net profit."
        elif edge > 0 and float(day.total_pnl) <= 0:
            key_signal = "Expectancy looks positive, but fees/variance produced a non-profitable net day."
        elif edge <= 0 and float(day.total_pnl) > 0:
            key_signal = "Net day was green, but expectancy is not positive—watch for fragile performance."
        else:
            key_signal = "Expectancy is not positive; focus on improving win/loss balance or win rate."

    summary_title = title or f"Daily Performance Summary — {day.date}"
    symbols = ", ".join(sorted(day.symbols_traded)) if day.symbols_traded else "—"

    text = (
        f"{summary_title}\n"
        f"Day: {label} | Net P&L: ${day.total_pnl:,.2f} (fees: ${day.fees:,.2f})\n"
        f"Trades: {trades} | Win rate: {day.win_rate:.1f}% | Avg win: ${day.avg_win:,.2f} | "
        f"Avg loss: ${day.avg_loss:,.2f} | W/L (avg): {win_loss_ratio:.2f}\n"
        f"Expectancy (net/trade): ${edge:,.2f} ({edge_signal})\n"
        f"Symbols: {symbols}\n"
        f"Signal: {key_signal}"
    )

    return {
        "date": day.date,
        "label": label,
        "metrics": {
            "win_rate_pct": float(day.win_rate),
            "avg_win": float(day.avg_win),
            "avg_loss": float(day.avg_loss),
            "win_loss_ratio": win_loss_ratio,
            "avg_fee_per_trade": avg_fee,
            **expectancy,
        },
        "thresholds": {
            "flat_pnl_abs": float(thresholds.flat_pnl_abs),
        },
        "text": text,
    }

