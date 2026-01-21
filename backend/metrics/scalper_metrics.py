"""
Gamma scalper precision metrics.

This module is intentionally lightweight and side-effect free. It is designed to be
used by simulation/backtest runners to accumulate per-event/per-intent diagnostics
and print a concise end-of-run summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.time.nyse_time import NYSE_TZ, parse_ts, to_nyse


def _dec(x: Any) -> Optional[Decimal]:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    try:
        s = str(x).strip()
        if not s:
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(x: Optional[Decimal]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    n = len(v)
    mid = n // 2
    if n % 2 == 1:
        return float(v[mid])
    return float((v[mid - 1] + v[mid]) / 2.0)


@dataclass
class GammaScalperPrecisionMetrics:
    """
    Collects and summarizes precision metrics for the 0DTE gamma scalper.

    Expected inputs:
    - `record_event(event, intents)` where:
      - `event` is a MarketEvent-like dict containing `ts`
      - `intents` are OrderIntent-like dicts returned by the strategy
    """

    exit_time_et: time = time(15, 45, 0)
    exit_tolerance_s: int = 60
    exit_tolerance_relaxed_s: int = 300

    # Event-level counts
    total_events: int = 0
    trade_events: int = 0  # events producing 1+ intents

    # Intent-level counts
    total_intents: int = 0
    hedge_intents: int = 0
    exit_intents: int = 0

    # Time span
    first_event_ts_utc: Optional[datetime] = None
    last_event_ts_utc: Optional[datetime] = None

    # Hedge sizing + delta residuals (share-equivalent)
    hedge_qty_abs: List[float] = field(default_factory=list)
    hedge_notional_abs: List[float] = field(default_factory=list)
    residual_delta_abs: List[float] = field(default_factory=list)
    overshoot_abs: List[float] = field(default_factory=list)
    undershoot_abs: List[float] = field(default_factory=list)

    # Time-to-exit accuracy (seconds; signed and absolute)
    exit_time_error_s: List[float] = field(default_factory=list)
    exit_time_abs_error_s: List[float] = field(default_factory=list)

    def record_event(self, event: Dict[str, Any], intents: Optional[Iterable[Dict[str, Any]]]) -> None:
        self.total_events += 1

        ts_raw = event.get("ts")
        try:
            ev_ts = parse_ts(ts_raw)
        except Exception:
            ev_ts = None

        if ev_ts is not None:
            if self.first_event_ts_utc is None or ev_ts < self.first_event_ts_utc:
                self.first_event_ts_utc = ev_ts
            if self.last_event_ts_utc is None or ev_ts > self.last_event_ts_utc:
                self.last_event_ts_utc = ev_ts

        intents_list = list(intents or [])
        if intents_list:
            self.trade_events += 1

        self.total_intents += len(intents_list)
        for intent in intents_list:
            self._record_intent(intent, fallback_event_ts=ev_ts)

    def _record_intent(self, intent: Dict[str, Any], fallback_event_ts: Optional[datetime]) -> None:
        client_tag = str(intent.get("client_tag") or "").strip().lower()
        md = intent.get("metadata") if isinstance(intent.get("metadata"), dict) else {}
        reason = str(md.get("reason") or "").strip().lower()

        is_exit = ("_exit" in client_tag) or (reason == "market_close_exit")
        is_hedge = ("_hedge" in client_tag) or (reason == "delta_hedge")

        if is_exit:
            self.exit_intents += 1
            self._record_exit_accuracy(intent, fallback_event_ts=fallback_event_ts)
            return

        if is_hedge:
            self.hedge_intents += 1
            self._record_hedge_precision(intent)
            return

    def _record_hedge_precision(self, intent: Dict[str, Any]) -> None:
        md = intent.get("metadata") if isinstance(intent.get("metadata"), dict) else {}

        net_delta_before = _dec(md.get("net_delta_before") or md.get("netDeltaBefore") or md.get("net_delta") or md.get("netDelta"))
        hedge_qty = _dec(md.get("hedge_qty") or md.get("hedgeQty") or md.get("qty"))
        underlying_price = _dec(md.get("underlying_price") or md.get("underlyingPrice") or md.get("price"))

        if hedge_qty is not None:
            self.hedge_qty_abs.append(abs(float(hedge_qty)))

        if hedge_qty is not None and underlying_price is not None:
            self.hedge_notional_abs.append(abs(float(hedge_qty * underlying_price)))

        if net_delta_before is None or hedge_qty is None:
            return

        # Residual share-equivalent delta after hedge (ideal is 0).
        residual = net_delta_before + hedge_qty
        self.residual_delta_abs.append(abs(float(residual)))

        # Overshoot vs undershoot classification:
        # - overshoot: hedge flips the delta sign (over-correct)
        # - undershoot: hedge reduces magnitude but keeps sign (under-correct)
        if residual == 0 or net_delta_before == 0:
            return
        if (net_delta_before > 0 and residual < 0) or (net_delta_before < 0 and residual > 0):
            self.overshoot_abs.append(abs(float(residual)))
        else:
            self.undershoot_abs.append(abs(float(residual)))

    def _record_exit_accuracy(self, intent: Dict[str, Any], fallback_event_ts: Optional[datetime]) -> None:
        # Prefer intent ts; fallback to the event ts.
        ts_raw = intent.get("ts")
        try:
            actual_ts = parse_ts(ts_raw) if ts_raw else fallback_event_ts
        except Exception:
            actual_ts = fallback_event_ts
        if actual_ts is None:
            return

        ny = to_nyse(actual_ts)
        target_ny = datetime.combine(ny.date(), self.exit_time_et, tzinfo=NYSE_TZ)
        target_utc = target_ny.astimezone(actual_ts.tzinfo)

        err_s = (actual_ts - target_utc).total_seconds()
        self.exit_time_error_s.append(float(err_s))
        self.exit_time_abs_error_s.append(float(abs(err_s)))

    def _duration_seconds(self) -> float:
        if self.first_event_ts_utc is None or self.last_event_ts_utc is None:
            return 0.0
        return max(0.0, (self.last_event_ts_utc - self.first_event_ts_utc).total_seconds())

    def summary(self) -> Dict[str, Any]:
        hold_events = self.total_events - self.trade_events
        duration_s = self._duration_seconds()
        duration_h = duration_s / 3600.0 if duration_s > 0 else 0.0

        trades_per_hour = (self.trade_events / duration_h) if duration_h > 0 else 0.0
        intents_per_hour = (self.total_intents / duration_h) if duration_h > 0 else 0.0

        hold_vs_trade_ratio = (hold_events / self.trade_events) if self.trade_events > 0 else float("inf")

        avg_hedge_qty = (sum(self.hedge_qty_abs) / len(self.hedge_qty_abs)) if self.hedge_qty_abs else 0.0
        avg_hedge_notional = (sum(self.hedge_notional_abs) / len(self.hedge_notional_abs)) if self.hedge_notional_abs else 0.0

        avg_residual_delta = (sum(self.residual_delta_abs) / len(self.residual_delta_abs)) if self.residual_delta_abs else 0.0
        median_residual_delta = _median(self.residual_delta_abs) if self.residual_delta_abs else 0.0

        overshoot_rate = (len(self.overshoot_abs) / self.hedge_intents) if self.hedge_intents > 0 else 0.0

        exit_mae = (sum(self.exit_time_abs_error_s) / len(self.exit_time_abs_error_s)) if self.exit_time_abs_error_s else 0.0
        exit_median_ae = _median(self.exit_time_abs_error_s) if self.exit_time_abs_error_s else 0.0
        exit_within = (
            sum(1 for x in self.exit_time_abs_error_s if x <= self.exit_tolerance_s) / len(self.exit_time_abs_error_s)
            if self.exit_time_abs_error_s
            else 0.0
        )
        exit_within_relaxed = (
            sum(1 for x in self.exit_time_abs_error_s if x <= self.exit_tolerance_relaxed_s) / len(self.exit_time_abs_error_s)
            if self.exit_time_abs_error_s
            else 0.0
        )

        return {
            "signal_frequency": {
                "events": self.total_events,
                "trade_events": self.trade_events,
                "duration_seconds": duration_s,
                "trade_events_per_hour": trades_per_hour,
                "intents_per_hour": intents_per_hour,
            },
            "hold_vs_trade": {
                "hold_events": hold_events,
                "trade_events": self.trade_events,
                "hold_to_trade_ratio": hold_vs_trade_ratio,
                "hold_pct": (hold_events / self.total_events) * 100.0 if self.total_events > 0 else 0.0,
            },
            "average_hedge_size": {
                "avg_abs_qty_shares": avg_hedge_qty,
                "avg_abs_notional": avg_hedge_notional,
                "hedge_intents": self.hedge_intents,
            },
            "delta_overshoot_undershoot": {
                "avg_abs_residual_delta": avg_residual_delta,
                "median_abs_residual_delta": median_residual_delta,
                "overshoot_rate": overshoot_rate,
                "overshoot_count": len(self.overshoot_abs),
                "undershoot_count": len(self.undershoot_abs),
            },
            "time_to_exit_accuracy": {
                "exit_intents": self.exit_intents,
                "mae_seconds": exit_mae,
                "median_ae_seconds": exit_median_ae,
                "within_tolerance_pct": exit_within * 100.0,
                "within_relaxed_tolerance_pct": exit_within_relaxed * 100.0,
                "tolerance_seconds": self.exit_tolerance_s,
                "relaxed_tolerance_seconds": self.exit_tolerance_relaxed_s,
            },
        }

    def format_report(self) -> str:
        s = self.summary()
        sf = s["signal_frequency"]
        hv = s["hold_vs_trade"]
        hs = s["average_hedge_size"]
        du = s["delta_overshoot_undershoot"]
        te = s["time_to_exit_accuracy"]

        dur_s = float(sf["duration_seconds"])
        dur_str = f"{dur_s:.0f}s" if dur_s < 3600 else f"{(dur_s/3600.0):.2f}h"

        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("GAMMA SCALPER — PRECISION METRICS SUMMARY")
        lines.append("=" * 80)
        lines.append("")

        lines.append("SIGNAL FREQUENCY:")
        lines.append(f"  Events:                {sf['events']}")
        lines.append(f"  Trade-events:          {sf['trade_events']}  (duration: {dur_str})")
        lines.append(f"  Trade-events / hour:   {sf['trade_events_per_hour']:.3f}")
        lines.append(f"  Intents / hour:        {sf['intents_per_hour']:.3f}")
        lines.append("")

        lines.append("HOLD vs TRADE:")
        lines.append(f"  HOLD events:           {hv['hold_events']}")
        lines.append(f"  TRADE events:          {hv['trade_events']}")
        lines.append(f"  HOLD%:                 {hv['hold_pct']:.2f}%")
        lines.append(f"  HOLD:TRADE ratio:      {hv['hold_to_trade_ratio']:.3f}" if hv["hold_to_trade_ratio"] != float("inf") else "  HOLD:TRADE ratio:      inf")
        lines.append("")

        lines.append("AVERAGE HEDGE SIZE (delta_hedge intents):")
        lines.append(f"  Hedge intents:         {hs['hedge_intents']}")
        lines.append(f"  Avg |qty| (shares):    {hs['avg_abs_qty_shares']:.3f}")
        lines.append(f"  Avg |notional|:        ${hs['avg_abs_notional']:.2f}")
        lines.append("")

        lines.append("DELTA OVERSHOOT / UNDERSHOOT (post-hedge residual):")
        lines.append(f"  Avg |residual|:        {du['avg_abs_residual_delta']:.3f} shares-delta")
        lines.append(f"  Median |residual|:     {du['median_abs_residual_delta']:.3f} shares-delta")
        lines.append(f"  Overshoot rate:        {du['overshoot_rate']*100.0:.2f}% ({du['overshoot_count']} overshoots / {self.hedge_intents} hedges)")
        lines.append("")

        lines.append("TIME-TO-EXIT ACCURACY (market close exit):")
        lines.append(f"  Exit intents:          {te['exit_intents']}")
        lines.append(f"  MAE:                   {te['mae_seconds']:.1f}s")
        lines.append(f"  Median AE:             {te['median_ae_seconds']:.1f}s")
        lines.append(f"  Within {te['tolerance_seconds']}s:          {te['within_tolerance_pct']:.1f}%")
        lines.append(f"  Within {te['relaxed_tolerance_seconds']}s:         {te['within_relaxed_tolerance_pct']:.1f}%")
        lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)

    def print_summary(self) -> None:
        print(self.format_report())

