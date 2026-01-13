"""
Performance Interpretation

Transforms raw daily trade performance metrics into human-readable signals.

Core outputs:
- expectancy (per-trade), derived from win rate + avg win/loss
- win rate
- average win / average loss
- daily label: "Profitable" / "Flat" / "Losing"
- explicit threshold logic used for labeling
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Tuple

from backend.analytics.trade_parser import DailyPnLSummary


def compute_expectancy_per_trade(
    *,
    win_rate_pct: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """
    Expectancy per trade (gross), using the standard win/loss decomposition:

      expectancy = p(win) * avg_win + p(loss) * avg_loss

    Conventions:
    - win_rate_pct is in [0, 100]
    - avg_win should be >= 0 (0 if no wins)
    - avg_loss should be <= 0 (0 if no losses)
    """
    p_win = float(win_rate_pct) / 100.0
    p_loss = 1.0 - p_win
    return (p_win * float(avg_win)) + (p_loss * float(avg_loss))


@dataclass(frozen=True, slots=True)
class ThresholdLogic:
    """
    Thresholds for mapping net daily P&L into a 3-state qualitative label.
    """

    flat_threshold_abs: float = 1.0

    def classify_daily(self, *, net_pnl: float) -> str:
        t = float(self.flat_threshold_abs)
        x = float(net_pnl)
        if x >= t:
            return "Profitable"
        if x <= -t:
            return "Losing"
        return "Flat"

    def to_dict(self) -> Dict[str, object]:
        t = float(self.flat_threshold_abs)
        return {
            "flat_threshold_abs": t,
            "profitable_if": f"net_pnl >= +{t}",
            "losing_if": f"net_pnl <= -{t}",
            "flat_if": f"-{t} < net_pnl < +{t}",
        }


@dataclass(frozen=True, slots=True)
class DailyPerformanceSignal:
    date: str
    label: str

    # Net P&L (after fees), consistent with DailyPnLSummary.total_pnl
    net_pnl: float

    # Raw trade stats (gross P&L based)
    trades_count: int
    win_rate: float
    avg_win: float
    avg_loss: float

    # Derived signals
    expectancy_gross_per_trade: float
    expectancy_net_per_trade: float


def interpret_daily_summaries(
    daily_summaries: Iterable[DailyPnLSummary],
    *,
    flat_threshold_abs: float = 1.0,
) -> Tuple[List[DailyPerformanceSignal], Mapping[str, object]]:
    """
    Convert DailyPnLSummary rows into human-readable daily signals plus threshold logic.
    """
    logic = ThresholdLogic(flat_threshold_abs=float(flat_threshold_abs))
    out: List[DailyPerformanceSignal] = []

    for d in daily_summaries:
        expectancy_gross = compute_expectancy_per_trade(
            win_rate_pct=float(d.win_rate),
            avg_win=float(d.avg_win),
            avg_loss=float(d.avg_loss),
        )
        expectancy_net = (float(d.total_pnl) / int(d.trades_count)) if d.trades_count > 0 else 0.0
        out.append(
            DailyPerformanceSignal(
                date=str(d.date),
                label=logic.classify_daily(net_pnl=float(d.total_pnl)),
                net_pnl=float(d.total_pnl),
                trades_count=int(d.trades_count),
                win_rate=float(d.win_rate),
                avg_win=float(d.avg_win),
                avg_loss=float(d.avg_loss),
                expectancy_gross_per_trade=float(expectancy_gross),
                expectancy_net_per_trade=float(expectancy_net),
            )
        )

    return out, logic.to_dict()

