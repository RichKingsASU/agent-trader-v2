from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


DayClassification = str  # "PROFITABLE" | "FLAT" | "LOSING"


@dataclass(frozen=True, slots=True)
class DailyInterpretationThresholds:
    """
    Threshold logic for interpreting a single trading day.

    We classify the day based on *net P&L* with a "flat band" around zero:
      - PROFITABLE if net_pnl > flat_band_abs
      - LOSING if net_pnl < -flat_band_abs
      - FLAT otherwise

    The flat band is adaptive (scaled to typical per-trade outcome magnitude) with
    a hard minimum floor so tiny P&L doesn't flip classifications.
    """

    # Minimum absolute net P&L required to call a day non-flat.
    flat_abs_floor_usd: float = 10.0

    # Adaptive component: flat band = max(floor, avg_abs_outcome * scale)
    flat_abs_scale_of_avg_trade: float = 0.25

    # Treat tiny realized outcomes as 0 (avoid noise / float artifacts).
    outcome_epsilon_usd: float = 1e-9


def compute_expectancy_per_trade(*, outcomes: Sequence[float]) -> float:
    """
    Expectancy (per trade) = average net outcome across realized trade outcomes.
    """
    if not outcomes:
        return 0.0
    return float(sum(outcomes) / len(outcomes))


def compute_win_rate(*, wins: int, losses: int) -> float:
    """
    Win rate as a percentage (0..100).
    """
    total = wins + losses
    if total <= 0:
        return 0.0
    return float(wins / total * 100.0)


def _avg_abs(values: Iterable[float]) -> float:
    vals = [abs(float(v)) for v in values]
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))


def flat_band_abs_usd(
    *,
    outcomes: Sequence[float],
    thresholds: DailyInterpretationThresholds = DailyInterpretationThresholds(),
) -> float:
    """
    Adaptive "flat day" band around 0 net P&L.
    """
    avg_abs_outcome = _avg_abs(outcomes)
    return float(max(thresholds.flat_abs_floor_usd, avg_abs_outcome * thresholds.flat_abs_scale_of_avg_trade))


def classify_day(
    *,
    net_pnl_usd: float,
    outcomes: Sequence[float],
    thresholds: DailyInterpretationThresholds = DailyInterpretationThresholds(),
) -> DayClassification:
    band = flat_band_abs_usd(outcomes=outcomes, thresholds=thresholds)
    if net_pnl_usd > band:
        return "PROFITABLE"
    if net_pnl_usd < -band:
        return "LOSING"
    return "FLAT"


def _fmt_usd(x: float) -> str:
    sign = "+" if x > 0 else ""
    return f"{sign}${x:,.2f}"


def format_daily_summary(
    *,
    date: str,
    day_classification: DayClassification,
    net_pnl_usd: float,
    gross_pnl_usd: float,
    fees_usd: float,
    wins: int,
    losses: int,
    win_rate_pct: float,
    avg_win_usd: float,
    avg_loss_usd: float,
    expectancy_usd_per_trade: float,
    symbols: Sequence[str],
) -> str:
    total = wins + losses
    syms = ", ".join(sorted(set(symbols))) if symbols else "-"
    return (
        f"{date} — {day_classification}: net {_fmt_usd(net_pnl_usd)} "
        f"(gross {_fmt_usd(gross_pnl_usd)}, fees ${fees_usd:,.2f}) • "
        f"{total} closes • WR {win_rate_pct:.1f}% ({wins}W/{losses}L) • "
        f"avg win {_fmt_usd(avg_win_usd)}, avg loss {_fmt_usd(avg_loss_usd)} • "
        f"expectancy {_fmt_usd(expectancy_usd_per_trade)}/trade • "
        f"symbols: {syms}"
    )

