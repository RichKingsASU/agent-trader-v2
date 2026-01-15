#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zzz-utbot_atr_live_1M_Rev_F22.py

SAFE / MINIMAL DIFF refactor notes (execution + marketdata only):
  - Broker-specific execution has been removed.
  - Entries/exits now EMIT AgentTrader TradeIntents (AgentIntent) instead of placing orders.
  - Alpaca free data only:
      * 1-minute bars stream (IEX) for underlying
      * options snapshots (indicative) for contract selection + limit pricing
  - No SIP, no tick/NBBO assumptions.
  - Limit prices are conservative: midpoint/last biased worse by LIMIT_BIAS_PCT (default 0.1%).
  - Paper-only safety: requires TRADING_MODE=paper and EXECUTION_MODE in {INTENT_ONLY, PAPER}.

Strategy logic, indicators, and signals are intentionally preserved.
"""

import os
import sys
import asyncio
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime, date
from typing import Optional, Dict, Any, Tuple, List
from uuid import uuid4

import pandas as pd
import ta
from ta.momentum import RSIIndicator

import requests

# Alpaca official SDK (alpaca-py): https://alpaca.markets/sdks/python/
# Source: https://github.com/alpacahq/alpaca-py.git
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.live import StockDataStream
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
except Exception as e:  # pragma: no cover
    StockHistoricalDataClient = None  # type: ignore[assignment]
    StockDataStream = None  # type: ignore[assignment]
    StockBarsRequest = None  # type: ignore[assignment]
    TimeFrame = None  # type: ignore[assignment]
    TimeFrameUnit = None  # type: ignore[assignment]
    _ALPACA_PY_IMPORT_ERR = e

# AgentTrader intent emission (non-executing).
try:
    from backend.trading.agent_intent import AgentIntent, emit_agent_intent
    from backend.trading.agent_intent.models import (
        AgentIntentConstraints,
        AgentIntentRationale,
        IntentAssetType,
        IntentKind,
        IntentSide,
        IntentOption,
        OptionRight,
    )
except Exception as e:  # pragma: no cover
    AgentIntent = None  # type: ignore[assignment]
    emit_agent_intent = None  # type: ignore[assignment]
    _AGENT_INTENT_IMPORT_ERR = e

# Strategy helper imports (unchanged from provided base code).
from ut_core_helper import (
    TZ_NY,
    ATR_PERIOD,
    Candle,
    StrictAggregator,
    MultiTFBuilder,
    TickFilter,
    compute_utbot_signal,
    compute_utbot_dynamic,
    analyze_wick,
    seed_utbot_from_history,
    PivotTapeState,
    print_pivot_tape,
    MarketStructure15,
)

# ✅ F18: use the V2 tick helper (hard-drop valve on MinuteHiLo)
#
# IMPORTANT: With Alpaca FREE data we receive *1-minute bars*, not tick prints.
# We keep these helpers intact but feed them with synthetic "ticks" derived from 1m closes.
from ut_tick_helper_v2 import (
    FastMoveDetector,
    MinuteHiLo,
    OneMinuteTickRSI,
)

# ✅ F19 engines
from continuation_engine import (
    Cont1State,
    process_continuation,
    cont_arm_after_dyn_exit,
    on_confirmed_ut_flip_maybe_cancel_cont1,
)
from last_hour_engine import (
    LastHourState,
    process_last_hour_trend,
    is_last_hour as is_last_hour_ny,
)

#
# NOTE: python-dotenv removed; this module relies on process env or Secret Manager-backed config.
#

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
CONTRACT_MULT = 100

RTH_TRADE_START = dtime(9, 30)
RTH_TRADE_END   = dtime(16, 0)   # end is EXCLUSIVE for trading/entries in F21+

EXT_TRADE_START = dtime(4, 0)   # 04:00 NY
EXT_TRADE_END   = dtime(20, 0)  # 20:00 NY

EOD_WINDOW_START = dtime(15, 58)
EOD_WINDOW_END   = dtime(16, 0)

RSI_ENTRY_MIN_DEFAULT = 33.0
RSI_ENTRY_MAX_DEFAULT = 58.0

RSI_EXIT_SOFT_DEFAULT = 3.0
RSI_EXIT_HARD_DEFAULT = 6.0

DEFAULT_STOPLOSS_PCT  = 0.005

FR20_DELTA_DEFAULT = 0.20
FR20_BUY_RSI5_MIN_DEFAULT  = 30.0
FR20_BUY_RSI1_MIN_DEFAULT  = 50.0
FR20_SELL_RSI5_MAX_DEFAULT = 70.0
FR20_SELL_RSI1_MAX_DEFAULT = 50.0

# F19 last-hour defaults (kept as constants to avoid CLI expansion for now)
LH_START = dtime(15, 0)         # last hour start
LH_END   = dtime(16, 0)
LH_MIN_STABLE_BARS = 2
LH_ALLOW_ONLY_ONE = True
LH_BLOCK_ON_FLIP_BAR = True

# F22 carry defaults
CARRY_BUY_MAX_RSI5_DEFAULT  = 72.0
CARRY_SELL_MIN_RSI5_DEFAULT = 28.0
CARRY_MAX_DIST_ATR_DEFAULT  = 2.0

# Execution refactor knobs (env-only to avoid CLI/parameter churn)
LIMIT_BIAS_PCT_DEFAULT = 0.001  # 0.1% default
ALPACA_STOCK_FEED = "iex"       # Alpaca free stock feed
ALPACA_OPTIONS_FEED_DEFAULT = "indicative"  # Alpaca free options snapshots feed


def _parse_timeframe(tf: Any) -> TimeFrame:
    """
    Adapter for helper code that historically used legacy timeframe strings
    like "1Min", "5Min", "15Min".
    """
    if tf is None:
        return TimeFrame.Minute
    s = str(tf).strip()
    if s.endswith("Min"):
        try:
            n = int(s[:-3])
            return TimeFrame(n, TimeFrameUnit.Minute)
        except Exception:
            return TimeFrame.Minute
    if s.endswith("Hour"):
        try:
            n = int(s[:-4])
            return TimeFrame(n, TimeFrameUnit.Hour)
        except Exception:
            return TimeFrame.Hour
    # Fall back (alpaca-py also accepts "1Min" strings in some contexts, but be strict)
    return TimeFrame.Minute


def _require_alpaca_py() -> None:
    if StockHistoricalDataClient is None or StockDataStream is None:
        raise RuntimeError(
            "alpaca-py is required but not importable. "
            "Install it from the official repo: "
            "pip install \"git+https://github.com/alpacahq/alpaca-py.git\" "
            f"(import error: {_ALPACA_PY_IMPORT_ERR!r})"
        )


class _AlpacaPyRestAdapter:
    """
    Minimal adapter so existing helper functions (e.g., `seed_utbot_from_history`)
    can continue calling `get_bars(...)` while the underlying API calls use alpaca-py.
    """

    def __init__(self, client: StockHistoricalDataClient, *, default_feed: str):
        self._client = client
        self._default_feed = str(default_feed).strip().lower() or ALPACA_STOCK_FEED

    def get_bars(self, symbol: str, timeframe: Any, start=None, end=None, limit: int | None = None, adjustment: str | None = None, feed: str | None = None, **_kwargs):  # noqa: ANN001
        req = StockBarsRequest(
            symbol_or_symbols=str(symbol).upper(),
            timeframe=_parse_timeframe(timeframe),
            start=start,
            end=end,
            limit=limit,
            adjustment=adjustment or "raw",
            feed=(str(feed).strip().lower() if feed else self._default_feed),
        )
        return self._client.get_stock_bars(req)


print("CWD:", os.getcwd())

# ─────────────────────────────────────────────────────────────
# FIRST-HOUR FILTER (CONFIRMED 15m flips only)  (F13 baseline preserved)
# ─────────────────────────────────────────────────────────────
Side = str  # "BUY" or "SELL"

def _side_ok(side: str) -> Side:
    s = str(side).upper().strip()
    if s not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got: {side!r}")
    return s

@dataclass
class FlipEvent:
    t: datetime
    side: Side

class FirstHourWindowSuppressor:
    """
    Candidate + reversal-within-window suppression (confirmed 15m only).

    During first hour:
      - first confirmed flip becomes candidate (no trade yet)
      - opposite within window => suppress both
      - if candidate survives window => release candidate (ALLOW) at current time
    """
    def __init__(self, rth_start: dtime, first_hour_minutes: int, window_minutes: int):
        self.rth_start = rth_start
        self.first_hour_minutes = int(first_hour_minutes)
        self.window_minutes = int(window_minutes)
        self._candidate: Optional[FlipEvent] = None

    def reset_day(self):
        self._candidate = None

    def _rth0(self, t: datetime) -> datetime:
        return datetime(
            t.year, t.month, t.day,
            self.rth_start.hour, self.rth_start.minute, self.rth_start.second,
            tzinfo=t.tzinfo
        )

    def _in_first_hour(self, t: datetime) -> bool:
        r0 = self._rth0(t)
        return r0 <= t < (r0 + timedelta(minutes=self.first_hour_minutes))

    def update_flip(self, t: datetime, side: Side) -> Dict[str, Any]:
        side = _side_ok(side)

        if not self._in_first_hour(t):
            self._candidate = None
            return {"allow": True, "side": side, "t_release": t, "reason": "outside_first_hour"}

        if self._candidate is None:
            self._candidate = FlipEvent(t=t, side=side)
            return {
                "allow": False,
                "reason": "candidate_set_wait_window",
                "candidate_side": side,
                "candidate_time": t,
                "deadline": t + timedelta(minutes=self.window_minutes),
            }

        if side == self._candidate.side:
            return {"allow": False, "reason": "same_side_while_candidate_active", "t": t, "side": side}

        deadline = self._candidate.t + timedelta(minutes=self.window_minutes)
        if t < deadline:
            old = self._candidate
            self._candidate = None
            return {
                "allow": False,
                "reason": "reversed_within_window_suppress_both",
                "first_side": old.side,
                "first_time": old.t,
                "reversal_side": side,
                "reversal_time": t,
                "deadline": deadline,
            }

        old = self._candidate
        self._candidate = None
        return {"allow": True, "side": old.side, "t_release": t, "reason": "candidate_survived_window"}

    def maybe_release_candidate(self, t: datetime) -> Optional[Dict[str, Any]]:
        if self._candidate is None:
            return None

        if not self._in_first_hour(t):
            old = self._candidate
            self._candidate = None
            return {"allow": True, "side": old.side, "t_release": t, "reason": "first_hour_over_release_candidate"}

        deadline = self._candidate.t + timedelta(minutes=self.window_minutes)
        if t >= deadline:
            old = self._candidate
            self._candidate = None
            return {"allow": True, "side": old.side, "t_release": t, "reason": "deadline_reached_release_candidate"}
        return None

class FirstHourConsec2Filter:
    def __init__(self, rth_start: dtime, first_hour_minutes: int):
        self.rth_start = rth_start
        self.first_hour_minutes = int(first_hour_minutes)
        self._candidate_side: Optional[Side] = None

    def reset_day(self):
        self._candidate_side = None

    def _rth0(self, t: datetime) -> datetime:
        return datetime(
            t.year, t.month, t.day,
            self.rth_start.hour, self.rth_start.minute, self.rth_start.second,
            tzinfo=t.tzinfo
        )

    def _in_first_hour(self, t: datetime) -> bool:
        r0 = self._rth0(t)
        return r0 <= t < (r0 + timedelta(minutes=self.first_hour_minutes))

    def update_flip(self, t: datetime, side: Side) -> Dict[str, Any]:
        side = _side_ok(side)

        if not self._in_first_hour(t):
            self._candidate_side = None
            return {"allow": True, "side": side, "t_release": t, "reason": "outside_first_hour"}

        if self._candidate_side is None:
            self._candidate_side = side
            return {"allow": False, "reason": "candidate_set_need_consec2", "candidate_side": side, "t": t}

        if side == self._candidate_side:
            self._candidate_side = None
            return {"allow": True, "side": side, "t_release": t, "reason": "consec2_confirmed"}

        self._candidate_side = side
        return {"allow": False, "reason": "streak_broken_new_candidate", "candidate_side": side, "t": t}

# ─────────────────────────────────────────────────────────────
# TIME GUARDS (F21: RTH end EXCLUSIVE)
# ─────────────────────────────────────────────────────────────
def is_eod_flatten_window(ts: datetime) -> bool:
    t = ts.astimezone(TZ_NY).time()
    # keep flatten inclusive through 16:00
    return (t >= EOD_WINDOW_START) and (t <= EOD_WINDOW_END)

def is_rth_time(ts: datetime) -> bool:
    """
    F21+: RTH is [09:30, 16:00) for trading logic.
    """
    t = ts.astimezone(TZ_NY).time()
    return (t >= RTH_TRADE_START) and (t < RTH_TRADE_END)

def is_after_rth_end(ts: datetime) -> bool:
    t = ts.astimezone(TZ_NY).time()
    return t >= RTH_TRADE_END

def parse_hhmm(s: str) -> dtime:
    hh, mm = s.split(":")
    return dtime(int(hh), int(mm))

def is_entry_time(ts: datetime, start_hhmm: str, args) -> bool:
    """
    F21+: End of window is EXCLUSIVE for both real & virtual so we never enter at 16:00:00.
    """
    t = ts.astimezone(TZ_NY).time()
    start_t = parse_hhmm(start_hhmm)

    # NOTE: --place-order is preserved but does NOT execute orders anymore.
    # It can be used by operators to indicate "intent emission" vs "print-only".
    if bool(getattr(args, "emit_intent", False)):
        end_t = RTH_TRADE_END
    else:
        end_t = EXT_TRADE_END

    return (t >= start_t) and (t < end_t)

# ─────────────────────────────────────────────────────────────
# FORMAT / NORMALIZE
# ─────────────────────────────────────────────────────────────
def norm_ts(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    pts = pd.Timestamp(ts)
    if pts.tzinfo is None:
        pts = pts.tz_localize("UTC")
    else:
        pts = pts.tz_convert("UTC")
    pts = pts.floor("s")
    return pts.to_pydatetime().astimezone(TZ_NY)

def f2(x: Any) -> str:
    return "na" if x is None else f"{float(x):.2f}"

def fmt_ts(ts: Any) -> str:
    t = norm_ts(ts)
    return "na" if t is None else t.isoformat()

def df_append_row(df: pd.DataFrame, row: Dict[str, Any], cols: list) -> pd.DataFrame:
    r = {k: row.get(k, None) for k in cols}
    if df.empty:
        return pd.DataFrame([r], columns=cols)
    df.loc[len(df)] = r
    return df

# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def build_arg_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="SPY")

    # Preserved for compatibility, but execution behavior changed:
    # - Previously: placed broker orders directly
    # - Now: emits AgentIntent messages (no broker orders are placed here)
    p.add_argument("--place-order", dest="emit_intent", action="store_true")

    p.add_argument("--exp", type=int, default=0, help="Expiration offset days (0=nearest/soonest)")
    p.add_argument("--amt", type=float, default=None, help="Target $ per buy (optional). If omitted qty=1.")

    p.add_argument("--rsi-exit-len", type=int, default=14)
    p.add_argument("--rsi-exit-soft", type=float, default=RSI_EXIT_SOFT_DEFAULT)
    p.add_argument("--rsi-exit-thresh", type=float, default=RSI_EXIT_HARD_DEFAULT)

    p.add_argument("--rsi5-exit", action="store_true",
                   help="If set, RSI5 setback can trigger exits (VIRTUAL/REAL). Otherwise print-only.")
    p.add_argument("--rsi5-debug", action="store_true",
                   help="(Optional) Extra RSI5 debug lines.")

    p.add_argument("--rsi-entry-min", type=float, default=RSI_ENTRY_MIN_DEFAULT)
    p.add_argument("--rsi-entry-max", type=float, default=RSI_ENTRY_MAX_DEFAULT)

    p.add_argument("--entry-mode", choices=["confirmed", "intrabar", "hybrid"], default="hybrid")

    p.add_argument("--rth-entry-start", default="09:36",
                   help="Earliest NY time to allow entries (HH:MM). Default 09:36")

    # ── F22: Carry entry (optional) ──
    p.add_argument("--rth-carry-entry", action="store_true",
                   help="Enable one-shot RTH carry entry (continuation-at-open) when UT regime is aligned and RSI/dist gates pass.")
    p.add_argument("--carry-buy-max-rsi5", type=float, default=CARRY_BUY_MAX_RSI5_DEFAULT,
                   help="BUY carry requires RSI5 <= this. Default 72.0")
    p.add_argument("--carry-sell-min-rsi5", type=float, default=CARRY_SELL_MIN_RSI5_DEFAULT,
                   help="SELL carry requires RSI5 >= this. Default 28.0")
    p.add_argument("--carry-max-dist-atr", type=float, default=CARRY_MAX_DIST_ATR_DEFAULT,
                   help="Carry requires dist(stop_ref) <= this * ATR15. Default 2.0")
    p.add_argument("--carry-debug", action="store_true",
                   help="Print extra carry debug lines each 1m while armed (when enabled).")

    p.add_argument("--intrabar-arm-threshold", type=float, default=0.10)
    p.add_argument("--intrabar-confirm-bars", type=int, default=2)

    p.add_argument("--stop-loss-pct", type=float, default=DEFAULT_STOPLOSS_PCT)
    p.add_argument("--spike-max-pct", type=float, default=0.08)

    p.add_argument("--tick-filter-window", type=int, default=10)
    p.add_argument("--tick-filter-pct", type=float, default=0.004)
    p.add_argument("--tick-filter-confirm", type=int, default=3)

    p.add_argument("--tick-clamp-pct", type=float, default=0.0,
                   help="Clamp each tick to +/- pct band around last accepted tick (0 disables). Example 0.003 = 0.3%")
    p.add_argument("--tick-clamp-mode", choices=["bars", "all"], default="bars",
                   help="bars = clamp only what feeds 1m/5m/15m builders; all = clamp tick helpers too")

    p.add_argument("--tick-rsi-len", type=int, default=120)
    p.add_argument("--tick-window", type=int, default=200)
    p.add_argument("--tick-cooldown", type=int, default=60)
    p.add_argument("--tick-atr-mult", type=float, default=0.50)
    p.add_argument("--tick-run-pct", type=float, default=0.0030)
    p.add_argument("--tick-drop-pct", type=float, default=0.0030)
    p.add_argument("--tick-run-pts", type=float, default=1.00)
    p.add_argument("--tick-drop-pts", type=float, default=1.00)
    p.add_argument("--tick-rsi-run", type=float, default=80.0)
    p.add_argument("--tick-rsi-drop", type=float, default=20.0)
    p.add_argument("--tick-debug", action="store_true")

    p.add_argument("--no-rsi1-step", action="store_true", help="Disable RSI1 step-back (enabled by default).")
    p.add_argument("--rsi1-exit", action="store_true", help="If set, RSI1 step-back can trigger exits (VIRTUAL/REAL).")
    p.add_argument("--rsi1-step", type=float, default=10.0)
    p.add_argument("--rsi1-arm-mins", type=int, default=0)
    p.add_argument("--rsi1-green-only", action="store_true", default=True)
    p.add_argument("--rsi1-allow-red", action="store_true", default=False)

    p.add_argument("--fr20", type=float, default=FR20_DELTA_DEFAULT)
    p.add_argument("--fr20-buy-rsi5-min", type=float, default=FR20_BUY_RSI5_MIN_DEFAULT)
    p.add_argument("--fr20-buy-rsi1-min", type=float, default=FR20_BUY_RSI1_MIN_DEFAULT)
    p.add_argument("--fr20-sell-rsi5-max", type=float, default=FR20_SELL_RSI5_MAX_DEFAULT)
    p.add_argument("--fr20-sell-rsi1-max", type=float, default=FR20_SELL_RSI1_MAX_DEFAULT)

    p.add_argument("--dump15", type=int, default=12,
                   help="How many closed 15m bars to dump each 15m close (0 disables).")

    # ── First-hour filter controls (F13) ──
    p.add_argument("--first-hour-filter", choices=["none", "window", "consec2"], default="window",
                   help="First-hour confirmed UT flip filter. Default 'window' for F13 baseline.")
    p.add_argument("--first-hour-minutes", type=int, default=60,
                   help="Scope of first hour from 09:30 NY (minutes). Default 60.")
    p.add_argument("--first-hour-window-minutes", type=int, default=45,
                   help="Window size used by 'window' filter mode. Default 45.")

    # ── FORCE OVERRIDE (F14) ──
    p.add_argument("--force-override", action="store_true",
                   help="Force a one-shot entry at/after --force-at (or NOW if omitted). Buyer beware.")
    p.add_argument("--force-side", choices=["CALL", "PUT"], default=None,
                   help="Side for forced entry (CALL or PUT). Required if --force-override.")
    p.add_argument("--force-at", default=None,
                   help="NY time HH:MM when force may fire. If omitted => NOW (NY).")

    # ── F15: Melt-up hold (CSTOP distance guard for RSI exits) ──
    p.add_argument("--melt-hold", action="store_true",
                   help="Enable CSTOP-distance guard to block RSI exits when cushion is intact.")
    p.add_argument("--melt-hold-dist-min", type=float, default=0.45,
                   help="Minimum favorable CLOSE-to-CSTOP distance (points) required to block RSI exits.")
    p.add_argument("--melt-hold-use-ratio", action="store_true",
                   help="Also require dist/distMax >= melt-hold-ratio-min to block RSI exits.")
    p.add_argument("--melt-hold-ratio-min", type=float, default=0.55,
                   help="If --melt-hold-use-ratio: require dist/distMax >= this (0..1).")

    # ── F16: DYN-RSI-EXIT (elastic threshold + proximity/shrink confirmation) ──
    p.add_argument("--dyn-rsi-exit", action="store_true",
                   help="Enable F16 elastic RSI5 exit (delta varies by RSI baseline) + confirm via CSTOP/DYN proximity/shrink.")
    p.add_argument("--rsi5-high", type=float, default=65.0)
    p.add_argument("--rsi5-low",  type=float, default=50.0)
    p.add_argument("--rsi5-delta-high", type=float, default=9.0)
    p.add_argument("--rsi5-delta-mid", type=float, default=6.0)
    p.add_argument("--rsi5-delta-low", type=float, default=4.5)
    p.add_argument("--dyn-prox-frac", type=float, default=0.45)
    p.add_argument("--dyn-shrink-frac", type=float, default=0.15)

    # ── F17: one-shot continuation after RSI5_DYN_EXIT ──
    p.add_argument("--cont1-after-dyn-exit", action="store_true",
                   help="Arm ONE continuation entry after an RSI5_DYN_EXIT (after cooldown) if UT-aligned.")
    p.add_argument("--cont1-cooldown-mins", type=float, default=3.0)
    p.add_argument("--cont1-ut-buffer", type=float, default=0.00)
    p.add_argument("--cont1-debug", action="store_true")

    return p

# ─────────────────────────────────────────────────────────────
# REMAINING STRATEGY IMPLEMENTATION (logic preserved; execution refactored)
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# STRUCTURE helpers (unchanged)
# ─────────────────────────────────────────────────────────────
def _pivot_high(df: pd.DataFrame, i: int, left: int, right: int) -> bool:
    if i - left < 0 or i + right >= len(df):
        return False
    h = float(df["h"].iloc[i])
    w = df["h"].iloc[i-left:i+right+1].astype(float)
    return h == float(w.max()) and (w == h).sum() == 1

def _pivot_low(df: pd.DataFrame, i: int, left: int, right: int) -> bool:
    if i - left < 0 or i + right >= len(df):
        return False
    l = float(df["l"].iloc[i])
    w = df["l"].iloc[i-left:i+right+1].astype(float)
    return l == float(w.min()) and (w == l).sum() == 1

def update_structure_5m(df5: pd.DataFrame, state: dict, left: int = 2, right: int = 2):
    if len(df5) < (left + right + 1):
        return None

    pivot_i = len(df5) - 1 - right

    try:
        t = df5.index[pivot_i]
    except Exception:
        t = df5["t"].iloc[pivot_i] if "t" in df5.columns else pivot_i

    if state.get("structure_last_pivot_t") == t:
        return None

    hi = float(df5["h"].iloc[pivot_i])
    lo = float(df5["l"].iloc[pivot_i])

    event = None

    if _pivot_high(df5, pivot_i, left, right):
        prev_hi = state.get("last_pivot_high")
        tag = "HH" if (prev_hi is None or hi > float(prev_hi)) else "LH"

        state["last_pivot_high"] = hi
        state["last_pivot_high_t"] = t
        state["last_pivot_high_tag"] = tag

        state["structure_last_tag"] = tag
        state["structure_last_t"] = t
        state["structure_last_px"] = hi
        state["structure_last_pivot_t"] = t

        event = {"kind": "HIGH", "tag": tag, "t": t, "px": hi}

    if _pivot_low(df5, pivot_i, left, right):
        prev_lo = state.get("last_pivot_low")
        tag = "HL" if (prev_lo is None or lo > float(prev_lo)) else "LL"

        state["last_pivot_low"] = lo
        state["last_pivot_low_t"] = t
        state["last_pivot_low_tag"] = tag

        state["structure_last_tag"] = tag
        state["structure_last_t"] = t
        state["structure_last_px"] = lo
        state["structure_last_pivot_t"] = t

        event = {"kind": "LOW", "tag": tag, "t": t, "px": lo}

    return event

# ─────────────────────────────────────────────────────────────
# PRINT helpers (unchanged)
# ─────────────────────────────────────────────────────────────
def print_5m_bar(c5: Candle, rsi5: Optional[float]):
    print(
        f"[5m][C] {fmt_ts(c5.end)} "
        f"O:{float(c5.o):.2f} H:{float(c5.h):.2f} L:{float(c5.l):.2f} C:{float(c5.c):.2f} "
        f"RSI5:{f2(rsi5)}"
    )

def print_15m_bar(c15: Candle, cstop: Optional[float], atr: Optional[float], buy: bool, sell: bool):
    print(
        f"[15m][C] {fmt_ts(c15.end)} "
        f"O:{float(c15.o):.2f} H:{float(c15.h):.2f} L:{float(c15.l):.2f} C:{float(c15.c):.2f}"
    )
    print(
        f"[15m][UT] {fmt_ts(c15.end)} "
        f"C:{float(c15.c):.2f} CSTOP:{f2(cstop)} ATR:{f2(atr)} Buy:{buy} Sell:{sell}"
    )

# ─────────────────────────────────────────────────────────────
# 15m DUMP HELPERS (unchanged)
# ─────────────────────────────────────────────────────────────
def compute_ut_snapshot(df15: pd.DataFrame, atr_period: int = ATR_PERIOD) -> Optional[pd.DataFrame]:
    if df15 is None or df15.empty or len(df15) < atr_period + 2:
        return None

    df2 = df15.sort_values("t").reset_index(drop=True).copy()
    src = df2["c"].astype(float)

    atr = ta.volatility.average_true_range(
        df2["h"].astype(float),
        df2["l"].astype(float),
        src,
        window=atr_period,
    )
    df2["ATR"] = atr

    stops = pd.Series(index=df2.index, dtype=float)

    for i in range(len(df2)):
        prev_stop = (src.iloc[0] - atr.iloc[0]) if i == 0 else stops.iloc[i - 1]

        if pd.isna(atr.iloc[i]):
            stops.iloc[i] = prev_stop
            continue

        prev_close = src.shift(1).iloc[i]
        this_close = src.iloc[i]

        if this_close > prev_stop and prev_close > prev_stop:
            stops.iloc[i] = max(prev_stop, this_close - atr.iloc[i])
        elif this_close < prev_stop and prev_close < prev_stop:
            stops.iloc[i] = min(prev_stop, this_close + atr.iloc[i])
        else:
            stops.iloc[i] = (this_close - atr.iloc[i]) if this_close > prev_stop else (this_close + atr.iloc[i])

    df2["CSTOP"] = stops
    df2["TVSTOP"] = stops
    return df2

def dump_last_15m(df15: pd.DataFrame, n: int = 12, atr_period: int = ATR_PERIOD):
    snap = compute_ut_snapshot(df15, atr_period=atr_period)
    if snap is None:
        print(f"[15m][DUMP] need >= {atr_period+2} bars (have {0 if df15 is None else len(df15)})")
        return

    tail = snap.tail(int(n)).copy()
    print(f"[15m][DUMP] last {len(tail)} closed 15m bars (NY end time):")
    for _, r in tail.iterrows():
        t = norm_ts(r["t"])
        print(
            f"  {t}  O:{float(r['o']):.2f} H:{float(r['h']):.2f} L:{float(r['l']):.2f} C:{float(r['c']):.2f}  "
            f"ATR:{f2(r['ATR'])}  CSTOP:{f2(r['CSTOP'])}  TVSTOP:{f2(r['TVSTOP'])}  Δ:{f2(float(r['TVSTOP'])-float(r['CSTOP']))}"
        )

    last = tail.iloc[-1]
    print(
        f"[15m][DUMP-LAST] t={norm_ts(last['t'])}  "
        f"C:{float(last['c']):.2f}  ATR:{f2(last['ATR'])}  CSTOP:{f2(last['CSTOP'])}  TVSTOP:{f2(last['TVSTOP'])}  "
        f"Δ:{f2(float(last['TVSTOP'])-float(last['CSTOP']))}"
    )

# ─────────────────────────────────────────────────────────────
# PRICE CLAMP (unchanged)
# ─────────────────────────────────────────────────────────────
def clamp_to_last(px: float, ref: float, pct: float) -> float:
    hi = ref * (1.0 + pct)
    lo = ref * (1.0 - pct)
    return min(max(px, lo), hi)

# ─────────────────────────────────────────────────────────────
# F15/F16 helpers (unchanged)
# ─────────────────────────────────────────────────────────────
def calc_cstop_distance(side: str, px_close: float, cstop: float) -> float:
    if str(side).upper() == "CALL":
        return float(px_close) - float(cstop)
    return float(cstop) - float(px_close)

def rsi5_elastic_threshold(base: Optional[float], args) -> float:
    if base is None:
        return float(getattr(args, "rsi5_delta_mid", args.rsi_exit_thresh))
    b = float(base)
    hi = float(getattr(args, "rsi5_high", 65.0))
    lo = float(getattr(args, "rsi5_low", 50.0))
    if b >= hi:
        return float(getattr(args, "rsi5_delta_high", 9.0))
    if b < lo:
        return float(getattr(args, "rsi5_delta_low", 4.5))
    return float(getattr(args, "rsi5_delta_mid", 6.0))

def dyn_rsi5_eval(
    side: str,
    px_close: float,
    base: Optional[float],
    rsi5: Optional[float],
    atr: Optional[float],
    cstop: Optional[float],
    dyn: Optional[float],
    dist_max: Optional[float],
    args
) -> Dict[str, Any]:
    out = {
        "enabled": bool(getattr(args, "dyn_rsi_exit", False)),
        "required": None,
        "delta": None,
        "fired": False,
        "ok": False,
        "why": "DISABLED",
        "dist_near": None,
        "prox": None,
        "shrink": None,
        "shrink_req": None,
    }

    if not out["enabled"]:
        return out

    if base is None or rsi5 is None:
        out["why"] = "NO_BASE_RSI"
        return out
    if atr is None or float(atr) <= 0:
        out["why"] = "NO_ATR"
        return out
    if cstop is None and dyn is None:
        out["why"] = "NO_STOPS"
        return out

    required = rsi5_elastic_threshold(base, args)
    out["required"] = float(required)

    d = float(rsi5) - float(base)
    out["delta"] = float(d)

    s = str(side).upper()
    if s == "CALL":
        fired = bool(d <= -float(required))
    else:
        fired = bool(d >= +float(required))
    out["fired"] = fired

    if not fired:
        out["why"] = "NO_FIRE"
        return out

    prox = float(getattr(args, "dyn_prox_frac", 0.45)) * float(atr)
    out["prox"] = float(prox)

    dists = []
    if cstop is not None:
        dists.append(calc_cstop_distance(s, float(px_close), float(cstop)))
    if dyn is not None:
        dists.append(calc_cstop_distance(s, float(px_close), float(dyn)))

    dist_near = float(min(dists)) if len(dists) else None
    out["dist_near"] = dist_near

    prox_ok = bool(dist_near is not None and dist_near <= prox)

    shrink_req = float(getattr(args, "dyn_shrink_frac", 0.15)) * float(atr)
    out["shrink_req"] = float(shrink_req)

    shrink = None
    shrink_ok = False
    if dist_near is not None and dist_max is not None and float(dist_max) > 0:
        shrink = float(dist_max) - float(dist_near)
        shrink_ok = bool(shrink >= shrink_req)
    out["shrink"] = shrink

    if prox_ok or shrink_ok:
        out["ok"] = True
        out["why"] = "OK_PROX" if prox_ok else "OK_SHRINK"
    else:
        out["ok"] = False
        out["why"] = "BLOCK_FAR"

    return out

# ─────────────────────────────────────────────────────────────
# F22: CARRY helpers (unchanged)
# ─────────────────────────────────────────────────────────────
def carry_stop_ref(regime: Optional[str], cstop: Optional[float], dyn: Optional[float]) -> Optional[float]:
    vals = [v for v in [cstop, dyn] if v is not None]
    if not vals:
        return None
    r = (regime or "").upper()
    if r == "SELL":
        return float(min(vals))
    return float(max(vals))

def carry_dist_points(regime: Optional[str], px: float, stop_ref: float) -> float:
    r = (regime or "").upper()
    if r == "SELL":
        return float(stop_ref) - float(px)
    return float(px) - float(stop_ref)

# ─────────────────────────────────────────────────────────────
# EXECUTION SAFETY + INTENT EMISSION
# ─────────────────────────────────────────────────────────────
def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or default).strip()

def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return float(default)
    try:
        return float(str(v).strip())
    except Exception:
        return float(default)

def _require_paper_only() -> None:
    """
    Paper-only guardrail.

    Required by task:
      - Respect TRADING_MODE=paper
      - Do not allow live execution paths
      - Must run in EXECUTION_MODE=INTENT_ONLY or PAPER
    """
    trading_mode = _env_str("TRADING_MODE", "paper").lower()
    exec_mode = _env_str("EXECUTION_MODE", "INTENT_ONLY").upper()

    if trading_mode != "paper":
        raise RuntimeError(f"Refusing to run: TRADING_MODE must be 'paper' (got {trading_mode!r})")
    if exec_mode not in {"INTENT_ONLY", "PAPER"}:
        raise RuntimeError(f"Refusing to run: EXECUTION_MODE must be INTENT_ONLY or PAPER (got {exec_mode!r})")

def _intent_deps_ok() -> None:
    if emit_agent_intent is None or AgentIntent is None:
        raise RuntimeError(f"AgentIntent import failed: {_AGENT_INTENT_IMPORT_ERR!r}")

def _alpaca_creds() -> Tuple[str, str]:
    """
    Resolve Alpaca credentials from environment.

    Supported patterns:
      - ALPACA_API_KEY / ALPACA_API_SECRET (preferred)
      - If ALPACA_ENV indicates sandbox/paper: ALPACA_SAND_KEY_ID / ALPACA_SAND_SECRET_KEY

    Safety: never log or print secrets.
    """
    key = _env_str("ALPACA_API_KEY", "")
    secret = _env_str("ALPACA_API_SECRET", "")
    if key and secret:
        return key, secret

    env = _env_str("ALPACA_ENV", "").lower()
    if env in {"sandbox", "paper"}:
        key = _env_str("ALPACA_SAND_KEY_ID", "")
        secret = _env_str("ALPACA_SAND_SECRET_KEY", "")
        if key and secret:
            return key, secret

    # Fall back to common variants (best-effort)
    key = _env_str("ALPACA_KEY_ID", "") or _env_str("APCA_API_KEY_ID", "")
    secret = _env_str("ALPACA_SECRET_KEY", "") or _env_str("APCA_API_SECRET_KEY", "")
    if key and secret:
        return key, secret

    raise RuntimeError(
        "Missing Alpaca credentials. Set either ALPACA_API_KEY+ALPACA_API_SECRET "
        "or (for sandbox/paper) ALPACA_ENV=sandbox with ALPACA_SAND_KEY_ID+ALPACA_SAND_SECRET_KEY."
    )

def _alpaca_headers() -> Dict[str, str]:
    key, secret = _alpaca_creds()
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

def _limit_bias_pct() -> float:
    return float(_env_float("LIMIT_BIAS_PCT", LIMIT_BIAS_PCT_DEFAULT))

def _bias_limit(*, base_px: float, intent_side: str) -> float:
    """
    Conservative limit bias:
      - BUY: raise limit (worse for buyer)
      - SELL: lower limit (worse for seller)
    """
    b = float(_limit_bias_pct())
    if float(base_px) <= 0:
        return float(base_px)
    s = str(intent_side).upper()
    if s == "BUY":
        return float(base_px) * (1.0 + b)
    if s == "SELL":
        return float(base_px) * (1.0 - b)
    return float(base_px)

def _snap_get_details(snap: Dict[str, Any]) -> Dict[str, Any]:
    d = snap.get("details") or {}
    return d if isinstance(d, dict) else {}

def _snap_expiration(snap: Dict[str, Any]) -> Optional[date]:
    d = _snap_get_details(snap)
    v = d.get("expiration_date") or d.get("expirationDate") or d.get("expiration")
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None

def _snap_strike(snap: Dict[str, Any]) -> Optional[float]:
    d = _snap_get_details(snap)
    v = d.get("strike_price") or d.get("strike") or d.get("strikePrice")
    try:
        return float(v)
    except Exception:
        return None

def _snap_right(snap: Dict[str, Any]) -> Optional[str]:
    d = _snap_get_details(snap)
    v = d.get("type") or d.get("option_type") or d.get("right")
    if not v:
        return None
    s = str(v).strip().upper()
    if s in {"CALL", "C"}:
        return "CALL"
    if s in {"PUT", "P"}:
        return "PUT"
    return None

def _snap_quote(snap: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    q = snap.get("latestQuote") or snap.get("latest_quote") or snap.get("quote") or {}
    if not isinstance(q, dict):
        return None, None
    bid = q.get("bp") or q.get("bid_price") or q.get("bidPrice") or q.get("bid")
    ask = q.get("ap") or q.get("ask_price") or q.get("askPrice") or q.get("ask")
    try:
        bid_f = float(bid) if bid is not None else None
    except Exception:
        bid_f = None
    try:
        ask_f = float(ask) if ask is not None else None
    except Exception:
        ask_f = None
    return bid_f, ask_f

def _snap_last(snap: Dict[str, Any]) -> Optional[float]:
    t = snap.get("latestTrade") or snap.get("latest_trade") or snap.get("trade") or {}
    if not isinstance(t, dict):
        return None
    p = t.get("p") or t.get("price") or t.get("last") or t.get("last_price")
    try:
        return float(p) if p is not None else None
    except Exception:
        return None

def _fetch_option_snapshots_underlying(*, underlying: str, feed: str) -> Dict[str, Any]:
    """
    Alpaca options snapshots (free feed).
      GET https://data.alpaca.markets/v1beta1/options/snapshots/{UNDERLYING}?feed=indicative
    """
    url = f"https://data.alpaca.markets/v1beta1/options/snapshots/{str(underlying).strip().upper()}"
    r = requests.get(url, headers=_alpaca_headers(), params={"feed": feed}, timeout=30)
    r.raise_for_status()
    payload = r.json() or {}
    snaps = payload.get("snapshots") or {}
    return snaps if isinstance(snaps, dict) else {}

def _pick_atm_option_from_snapshots(
    *,
    underlying: str,
    want_right: str,   # "CALL" or "PUT"
    exp_offset_days: int,
    underlying_px: float,
    feed: str,
) -> Optional[Dict[str, Any]]:
    snaps = _fetch_option_snapshots_underlying(underlying=underlying, feed=feed)
    if not snaps:
        return None

    want_right = str(want_right).upper().strip()
    today = datetime.now(tz=datetime.utcnow().astimezone().tzinfo).date()

    candidates: List[Tuple[int, float, str, Dict[str, Any]]] = []
    for sym, snap in snaps.items():
        if not isinstance(snap, dict):
            continue
        exp = _snap_expiration(snap)
        strike = _snap_strike(snap)
        right = _snap_right(snap)
        if exp is None or strike is None or right is None:
            continue
        if right != want_right:
            continue
        dte = (exp - today).days
        if dte < int(exp_offset_days):
            continue
        # primary sort: smallest DTE >= offset, secondary: strike distance
        candidates.append((int(dte), abs(float(strike) - float(underlying_px)), str(sym).upper(), snap))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]))
    dte, _dist, sym, snap = candidates[0]
    exp = _snap_expiration(snap)
    strike = _snap_strike(snap)
    right = _snap_right(snap)
    bid, ask = _snap_quote(snap)
    last = _snap_last(snap)
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (float(bid) + float(ask)) / 2.0

    return {
        "symbol": sym,
        "expiration": exp,
        "strike": strike,
        "right": right,
        "dte": dte,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": last,
        "raw": snap,
    }

def emit_trade_intent(intent: AgentIntent) -> None:
    """
    Execution change: this replaces all direct order placement.
    """
    _intent_deps_ok()
    emit_agent_intent(intent)

def _make_agent_intent(
    *,
    strategy_name: str,
    symbol: str,
    side: str,  # "BUY" or "SELL"
    kind: str,  # "DIRECTIONAL" or "EXIT"
    option_contract: Dict[str, Any],
    limit_price: Optional[float],
    short_reason: str,
    indicators: Dict[str, Any],
    valid_for_s: int = 120,
) -> AgentIntent:
    _intent_deps_ok()
    now_utc = datetime.utcnow().replace(microsecond=0)
    valid_until = now_utc + timedelta(seconds=int(valid_for_s))

    repo_id = _env_str("REPO_ID", "agent-trader-v2")
    agent_name = _env_str("AGENT_NAME", "utbot-strategy")
    corr = _env_str("CORRELATION_ID", "") or str(uuid4())

    exp: date = option_contract["expiration"]
    right: str = option_contract["right"]
    strike: float = float(option_contract["strike"])
    contract_symbol: str = option_contract["symbol"]

    opt = IntentOption(
        expiration=exp,
        right=OptionRight.CALL if right == "CALL" else OptionRight.PUT,
        strike=float(strike),
        contract_symbol=str(contract_symbol),
    )

    constraints = AgentIntentConstraints(
        valid_until_utc=valid_until,
        requires_human_approval=True,  # Safe default for INTENT_ONLY / shadow operation
        order_type="limit",
        time_in_force="day",
        limit_price=float(limit_price) if (limit_price is not None and float(limit_price) > 0) else None,
    )

    return AgentIntent(
        repo_id=repo_id,
        agent_name=agent_name,
        strategy_name=strategy_name,
        strategy_version=None,
        correlation_id=corr,
        symbol=str(symbol).upper(),
        asset_type=IntentAssetType.OPTION,
        option=opt,
        kind=IntentKind.EXIT if str(kind).upper() == "EXIT" else IntentKind.DIRECTIONAL,
        side=IntentSide.SELL if str(side).upper() == "SELL" else IntentSide.BUY,
        confidence=None,
        rationale=AgentIntentRationale(short_reason=str(short_reason), indicators=dict(indicators or {})),
        constraints=constraints,
    )

# ─────────────────────────────────────────────────────────────
# ENTRY/EXIT HELPERS (strategy triggers unchanged; execution=INTENT)
# ─────────────────────────────────────────────────────────────
def build_fake_contract(symbol: str, px: float, side: str) -> str:
    strike = int(round(px))
    return f"{symbol}_{strike}_{'C' if side == 'CALL' else 'P'}"

def qty_from_budget(amt: Optional[float], ask: Optional[float], limit_px: Optional[float]) -> int:
    # Kept for logging parity only (AgentIntent intentionally has no qty).
    if amt is None:
        return 1
    px = None
    if ask is not None and ask > 0:
        px = float(ask)
    elif limit_px is not None and limit_px > 0:
        px = float(limit_px)
    if px is None or px <= 0:
        return 1
    cost_per = px * CONTRACT_MULT
    if cost_per <= 0:
        return 1
    q = int(float(amt) // cost_per)
    return max(1, q)

async def do_entry(
    side,
    bar1m,
    args,
    origin,
    bypass_entry_window: bool = False,
):
    """
    Execution change:
      - Previously: selected/placed broker orders.
      - Now: selects a contract via Alpaca options snapshots and emits an AgentIntent.
    """
    _require_paper_only()

    ts = norm_ts(bar1m["t"])
    under_px = float(bar1m["c"])

    # F21+: hard stop on/after 16:00 for all entries (virtual or real)
    if is_after_rth_end(ts):
        print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE ts={ts} side={side} origin={origin}")
        return None, 0, None, "AFTER_CLOSE", None

    if (not bypass_entry_window) and (not is_entry_time(ts, args.rth_entry_start, args)):
        print(f"[ENTRY][BLOCKED] outside entry window start={args.rth_entry_start} ts={ts}")
        return None, 0, None, "ENTRY_WINDOW", None

    # Options selection uses Alpaca FREE snapshots (no NBBO assumptions).
    opt_feed = _env_str("ALPACA_OPTIONS_FEED", ALPACA_OPTIONS_FEED_DEFAULT).lower()
    want_right = "CALL" if str(side).upper() == "CALL" else "PUT"
    opt = _pick_atm_option_from_snapshots(
        underlying=str(args.symbol).upper(),
        want_right=want_right,
        exp_offset_days=int(args.exp),
        underlying_px=float(under_px),
        feed=opt_feed,
    )
    if not opt:
        contract = build_fake_contract(args.symbol, under_px, side)
        qty = qty_from_budget(args.amt, ask=None, limit_px=None)
        print(f"[ENTRY][NO-SNAPSHOT] {side} {contract} qty={qty} entry={under_px:.2f} origin={origin} t={ts} (NO_INTENT)")
        return None, 0, None, "NO_SNAPSHOT", None

    base_px = opt.get("mid") or opt.get("last")
    if base_px is None or float(base_px) <= 0:
        print(f"[ENTRY][FAIL] no usable price for {opt.get('symbol')} (mid/last missing)")
        return None, 0, None, "NO_PRICE", None

    # Conservative limit pricing: midpoint/last, biased worse by LIMIT_BIAS_PCT (default 0.1%).
    limit_px = _bias_limit(base_px=float(base_px), intent_side="BUY")
    bid, ask = opt.get("bid"), opt.get("ask")
    qty = qty_from_budget(args.amt, ask=float(ask) if ask is not None else None, limit_px=float(limit_px))

    print(
        f"[ENTRY][INTENT] BUY {opt['symbol']} x{qty} @ {float(limit_px):.2f} "
        f"(base={'mid' if opt.get('mid') is not None else 'last'}={float(base_px):.2f} bias={_limit_bias_pct()*100:.3f}%) "
        f"dte={opt.get('dte')} exp={opt.get('expiration')} strike={opt.get('strike')} "
        f"bid={f2(bid)} ask={f2(ask)} origin={origin} t={ts}"
    )

    intent = _make_agent_intent(
        strategy_name="zzz-utbot_atr_live_1M_Rev_F22",
        symbol=str(args.symbol).upper(),
        side="BUY",
        kind="DIRECTIONAL",
        option_contract=opt,
        limit_price=float(limit_px),
        short_reason=f"ENTRY {side} origin={origin}",
        indicators={"underlying_px": float(under_px), "origin": str(origin), "right": want_right},
    )
    emit_trade_intent(intent)
    return str(opt["symbol"]), int(qty), float(under_px), "INTENT", opt

async def do_exit(args, contract, qty, entry_px, side, bar1m, reason, origin, active_opt: Optional[Dict[str, Any]]):
    """
    Execution change: emits an EXIT intent (SELL) with conservative limit pricing.
    """
    _require_paper_only()

    ts = norm_ts(bar1m["t"])
    under_px = float(bar1m["c"])

    # Compute "shadow" PnL on underlying (logic preserved).
    pnl = (under_px - entry_px) if side == "CALL" else (entry_px - under_px)
    pnl_d = pnl * CONTRACT_MULT * float(qty or 1)

    if not active_opt:
        print(
            f"[EXIT][NO-OPT] {side} {contract} entry={entry_px:.2f} exit={under_px:.2f} "
            f"Δ={pnl:+.2f} PnL≈${pnl_d:+.2f} reason={reason} origin={origin} t={ts} (NO_INTENT)"
        )
        return True

    # Refresh the specific contract snapshot (free options snapshots).
    opt_feed = _env_str("ALPACA_OPTIONS_FEED", ALPACA_OPTIONS_FEED_DEFAULT).lower()
    try:
        snaps = _fetch_option_snapshots_underlying(underlying=str(args.symbol).upper(), feed=opt_feed)
        snap = snaps.get(str(active_opt["symbol"]).upper()) if isinstance(snaps, dict) else None
        if isinstance(snap, dict):
            bid, ask = _snap_quote(snap)
            last = _snap_last(snap)
            mid = (float(bid) + float(ask)) / 2.0 if (bid is not None and ask is not None and bid > 0 and ask > 0) else None
        else:
            bid, ask, last, mid = None, None, None, None
    except Exception:
        bid, ask, last, mid = None, None, None, None

    base_px = mid or last or active_opt.get("mid") or active_opt.get("last")
    if base_px is None or float(base_px) <= 0:
        base_px = 0.01  # extremely conservative fallback to avoid "perfect fill" assumptions

    limit_px = _bias_limit(base_px=float(base_px), intent_side="SELL")

    print(
        f"[EXIT][INTENT] SELL {active_opt['symbol']} x{qty} @ {float(limit_px):.2f} "
        f"(base={'mid' if mid is not None else 'last'}={float(base_px):.2f} bias={_limit_bias_pct()*100:.3f}%) "
        f"Δu={pnl:+.2f} PnL≈${pnl_d:+.2f} reason={reason} origin={origin} t={ts}"
    )

    intent = _make_agent_intent(
        strategy_name="zzz-utbot_atr_live_1M_Rev_F22",
        symbol=str(args.symbol).upper(),
        side="SELL",
        kind="EXIT",
        option_contract=active_opt,
        limit_price=float(limit_px) if float(limit_px) > 0 else None,
        short_reason=f"EXIT {side} reason={reason} origin={origin}",
        indicators={"underlying_px": float(under_px), "reason": str(reason), "origin": str(origin)},
    )
    emit_trade_intent(intent)
    return True

# ─────────────────────────────────────────────────────────────
# MAIN LIVE LOOP (Alpaca FREE 1-minute bars; logic preserved)
# ─────────────────────────────────────────────────────────────
async def run_live(args):
    # dotenv removed (no-op)
    _require_paper_only()
    _intent_deps_ok()
    _require_alpaca_py()

    state: Dict[str, Any] = {}

    alpaca_key, alpaca_secret = _alpaca_creds()

    # alpaca-py historical client (free data compatible)
    stock_hist = StockHistoricalDataClient(alpaca_key, alpaca_secret)
    rest = _AlpacaPyRestAdapter(stock_hist, default_feed=ALPACA_STOCK_FEED)

    builder_5m  = MultiTFBuilder("5m", 5)
    builder_15m = MultiTFBuilder("15m", 15)

    cols = ["t", "o", "h", "l", "c"]
    df5  = pd.DataFrame(columns=cols)
    df15 = pd.DataFrame(columns=cols)

    last_5m_rsi: Optional[float] = None
    last_cstop: Optional[float] = None
    last_cstop_dyn: Optional[float] = None
    last_atr: Optional[float] = None

    # F17: last confirmed UT flip side (regime gate)
    last_confirmed_ut_flip: Optional[str] = None  # "BUY"|"SELL"|None

    # F19: confirmed UT regime + stability tracking for last-hour engine
    ut_regime: Optional[str] = None               # "BUY"|"SELL"|None
    ut_stable_bars: int = 0
    ut_flip_now: bool = False

    active_side: Optional[str] = None
    active_contract: Optional[str] = None
    active_opt: Optional[Dict[str, Any]] = None
    active_qty: int = 1
    active_entry_px: Optional[float] = None
    active_origin: Optional[str] = None
    active_entry_ts: Optional[datetime] = None

    # F15/F16: distance tracker (we reuse for melt-hold AND dyn shrink confirmation)
    melt_dist_max: Optional[float] = None

    # F22: carry one-shot state + seeded regime
    carry_used_today: bool = False
    carry_seed_regime: Optional[str] = None  # "BUY"|"SELL"|None

    # RSI1 step-back state
    rsi1_extreme: Optional[float] = None
    rsi1_extreme_ts: Optional[datetime] = None
    rsi1_armed: bool = False

    def rsi1_reset_state():
        nonlocal rsi1_extreme, rsi1_extreme_ts, rsi1_armed
        rsi1_extreme = None
        rsi1_extreme_ts = None
        rsi1_armed = False

    # RSI5 baseline state
    rsi5_base: Optional[float] = None
    rsi5_base_ts: Optional[datetime] = None
    rsi5_base_pending: bool = False

    def rsi5_reset_state():
        nonlocal rsi5_base, rsi5_base_ts, rsi5_base_pending
        rsi5_base = None
        rsi5_base_ts = None
        rsi5_base_pending = False

    def rsi5_on_entry(now_ts: datetime):
        nonlocal rsi5_base, rsi5_base_ts, rsi5_base_pending, last_5m_rsi
        if last_5m_rsi is not None:
            rsi5_base = float(last_5m_rsi)
            rsi5_base_ts = now_ts
            rsi5_base_pending = False
            print(f"[RSI5][BASE] baseline={rsi5_base:.2f} @ {rsi5_base_ts}")
        else:
            rsi5_base = None
            rsi5_base_ts = None
            rsi5_base_pending = True
            print("[RSI5][BASE] baseline=None (pending until first RSI5)")

    def rsi5_arm_baseline_if_needed(now_ts: datetime):
        nonlocal rsi5_base, rsi5_base_ts, rsi5_base_pending, last_5m_rsi
        if rsi5_base_pending and (rsi5_base is None) and (last_5m_rsi is not None):
            rsi5_base = float(last_5m_rsi)
            rsi5_base_ts = now_ts
            rsi5_base_pending = False
            print(f"[RSI5][BASE-ARM] baseline={rsi5_base:.2f} @ {rsi5_base_ts}")

    def state_str(last_px: Optional[float]) -> str:
        if active_side is None or active_contract is None or active_entry_px is None:
            base = "FLAT"
        else:
            u = None
            if last_px is not None:
                u = (float(last_px) - float(active_entry_px)) if active_side == "CALL" else (float(active_entry_px) - float(last_px))
            u_s = f" uΔ={u:+.2f}" if u is not None else ""
            base = f"{active_side} {active_contract} qty={active_qty} entry={active_entry_px:.2f}{u_s}"

        try:
            st_tag = state.get("structure_last_tag")
            st_t   = state.get("structure_last_t")
            if st_tag and st_t is not None:
                tt = pd.Timestamp(st_t)
                base += f" STRUCT={st_tag}@{tt.strftime('%H:%M')}"
        except Exception:
            pass

        return base

    # ── F19: engine states (CONT1 + LASTHOUR) ──
    cont = Cont1State()
    lh = LastHourState()

    def cont_reset_day():
        nonlocal cont
        cont = Cont1State()

    def lh_reset_day():
        nonlocal lh, ut_regime, ut_stable_bars, ut_flip_now
        lh = LastHourState()
        ut_regime = None
        ut_stable_bars = 0
        ut_flip_now = False

    # ── F14: force override one-shot state ──
    did_force_entry: bool = False
    if bool(getattr(args, "force_override", False)):
        if not getattr(args, "force_side", None):
            print("[FORCE][ERR] --force-override requires --force-side CALL|PUT")
            sys.exit(2)
        if not getattr(args, "force_at", None):
            now_ny = datetime.now(TZ_NY).time()
            args.force_at = f"{now_ny.hour:02d}:{now_ny.minute:02d}"
            print(f"[FORCE] --force-at not provided -> default NOW (NY) = {args.force_at}")

    # ── F13: first-hour filter instance ──
    fh_filter = None
    if getattr(args, "first_hour_filter", "none") == "none":
        fh_filter = None
    elif args.first_hour_filter == "window":
        fh_filter = FirstHourWindowSuppressor(
            rth_start=RTH_TRADE_START,
            first_hour_minutes=int(args.first_hour_minutes),
            window_minutes=int(args.first_hour_window_minutes),
        )
    else:
        fh_filter = FirstHourConsec2Filter(
            rth_start=RTH_TRADE_START,
            first_hour_minutes=int(args.first_hour_minutes),
        )
    if fh_filter is not None:
        fh_filter.reset_day()

    last_day_key: Optional[str] = None
    def maybe_day_reset(ts_ny: datetime):
        nonlocal last_day_key, did_force_entry, fh_filter, last_confirmed_ut_flip
        nonlocal active_side, active_contract, active_opt, active_qty, active_entry_px, active_origin, active_entry_ts
        nonlocal melt_dist_max
        nonlocal rsi5_base, rsi5_base_ts, rsi5_base_pending
        nonlocal rsi1_extreme, rsi1_extreme_ts, rsi1_armed
        nonlocal ut_regime, ut_stable_bars, ut_flip_now
        nonlocal carry_used_today, carry_seed_regime

        key = ts_ny.astimezone(TZ_NY).strftime("%Y-%m-%d")
        if last_day_key is None:
            last_day_key = key
            return
        if key != last_day_key:
            last_day_key = key
            did_force_entry = False
            last_confirmed_ut_flip = None
            cont_reset_day()
            lh_reset_day()
            carry_used_today = False
            carry_seed_regime = None
            if fh_filter is not None:
                fh_filter.reset_day()
            print(f"[DAY] reset {key} (force re-armed, FH filter reset, CONT reset, LH reset, CARRY reset, UT stability reset)")

    # Tick helpers are retained but driven by 1m closes (no tick/NBBO assumptions).
    tick_filter = TickFilter(args.tick_filter_window, args.tick_filter_pct, args.tick_filter_confirm)
    last_good_tick_px: Optional[float] = None
    tick_hilo = MinuteHiLo(label="BAR1M", debug=True)

    fast = FastMoveDetector(
        tick_window=args.tick_window,
        rsi_len=args.tick_rsi_len,
        drop_pct=args.tick_drop_pct,
        run_pct=args.tick_run_pct,
        drop_pts=args.tick_drop_pts,
        run_pts=args.tick_run_pts,
        rsi_drop=args.tick_rsi_drop,
        rsi_run=args.tick_rsi_run,
        cooldown_s=args.tick_cooldown,
        use_anchor=True,
        debug=bool(args.tick_debug),
        label="BAR1M-RSI",
    )

    rsi_1m = OneMinuteTickRSI(rsi_len=14, label="RSI-1M", debug=bool(args.tick_debug))
    last_tick_rsi: Optional[float] = None
    last_rsi_1m: Optional[float] = None

    pivot_tape = PivotTapeState()
    ms15 = MarketStructure15(zigzag_len=40)

    # Seed (unchanged)
    df15, df5, init_sig, seeded_rsi = seed_utbot_from_history(
        rest,
        args.symbol,
        df15,
        df5,
        builder_5m=builder_5m,
        builder_15m=builder_15m,
        rsi_exit_len=args.rsi_exit_len,
        spike_max_pct=args.spike_max_pct,
        atr_period=ATR_PERIOD,
    )
    if seeded_rsi is not None:
        last_5m_rsi = float(seeded_rsi)

    ms15.update(df15)
    pivot_tape = PivotTapeState()
    print("[MS15] primed from seeded history (printing new pivots only)")

    if init_sig:
        last_cstop = float(init_sig["cstop"])
        last_cstop_dyn = float(init_sig["cstop"])
        last_atr = float(init_sig["atr"])

        # F22: derive seeded regime from last seeded 15m close vs stop (if possible)
        try:
            if df15 is not None and (not df15.empty) and ("c" in df15.columns) and last_cstop is not None:
                last_close = float(df15["c"].astype(float).iloc[-1])
                carry_seed_regime = "BUY" if last_close >= float(last_cstop) else "SELL"
                ut_regime = carry_seed_regime
                ut_stable_bars = max(int(LH_MIN_STABLE_BARS), 2)
                ut_flip_now = False
                print(f"[CARRY][SEED] regime={carry_seed_regime} lastC={last_close:.2f} cstop={float(last_cstop):.2f}")
        except Exception:
            pass

    # Alpaca stream: FREE 1-minute bars (IEX) via alpaca-py
    stream = StockDataStream(alpaca_key, alpaca_secret, feed=ALPACA_STOCK_FEED)

    async def on_bar(bar):
        nonlocal df5, df15
        nonlocal last_5m_rsi, last_cstop, last_cstop_dyn, last_atr
        nonlocal active_side, active_contract, active_opt, active_qty, active_entry_px, active_origin, active_entry_ts
        nonlocal last_tick_rsi, last_rsi_1m
        nonlocal last_good_tick_px
        nonlocal rsi1_extreme, rsi1_extreme_ts, rsi1_armed
        nonlocal rsi5_base, rsi5_base_ts, rsi5_base_pending
        nonlocal pivot_tape, ms15
        nonlocal state
        nonlocal fh_filter
        nonlocal did_force_entry
        nonlocal melt_dist_max
        nonlocal last_confirmed_ut_flip
        nonlocal cont, lh
        nonlocal ut_regime, ut_stable_bars, ut_flip_now
        nonlocal carry_used_today, carry_seed_regime

        # Bar timestamps are already minute-aligned.
        ts = norm_ts(getattr(bar, "timestamp", None) or getattr(bar, "t", None))
        if ts is None:
            return

        maybe_day_reset(ts)

        o = float(getattr(bar, "open"))
        h = float(getattr(bar, "high"))
        l = float(getattr(bar, "low"))
        c = float(getattr(bar, "close"))
        v1 = float(getattr(bar, "volume", 0.0) or 0.0)

        # Feed the "tick" helpers with the 1m close (no tick-level data).
        raw_px_in = float(c)
        tick_size = float(v1)

        try:
            filt = tick_filter.filter_tick(ts, raw_px_in, atr15=last_atr)
        except TypeError:
            filt = tick_filter.filter_tick(ts, raw_px_in)

        if filt is None:
            return

        ts, clean_px = filt
        raw_px = float(clean_px)
        if last_good_tick_px is None:
            last_good_tick_px = float(raw_px)

        clamp_on = bool(getattr(args, "tick_clamp_pct", 0) and args.tick_clamp_pct > 0)
        clamped_px = float(raw_px)
        if clamp_on:
            clamped_px = float(clamp_to_last(raw_px, float(last_good_tick_px), float(args.tick_clamp_pct)))
        use_px = float(clamped_px) if clamp_on else float(raw_px)
        last_good_tick_px = float(use_px)

        finalized, px_ok = tick_hilo.on_tick(ts, float(use_px))
        if px_ok is None:
            return

        _evt, tick_rsi = fast.update(ts, float(px_ok), atr15=last_atr, atr_mult=getattr(args, "tick_atr_mult", None))
        if tick_rsi is not None:
            last_tick_rsi = float(tick_rsi)
        m = rsi_1m.on_tick(ts, float(px_ok))
        if m:
            _mts, _close, r = m
            if r is not None:
                last_rsi_1m = float(r)

        # 1m bar (already closed)
        bar_t = norm_ts(ts).replace(second=0, microsecond=0)
        bar1m = {"t": bar_t, "o": o, "h": h, "l": l, "c": c, "v": v1}

        # FORCE OVERRIDE (unchanged; now emits intent via do_entry)
        if bool(getattr(args, "force_override", False)) and (not did_force_entry):
            try:
                force_t = parse_hhmm(str(args.force_at))
                if bar_t.astimezone(TZ_NY).time() >= force_t:
                    if active_side is None:
                        fs = str(args.force_side).upper().strip()
                        side = "CALL" if fs == "CALL" else "PUT"
                        print(f"[FORCE] FIRE t={bar_t} side={side} (force-at={args.force_at})")
                        contract, qty, entry_px, _oid, opt = await do_entry(
                            side, bar1m, args, f"FORCE__{args.force_at}", bypass_entry_window=True
                        )
                        if contract is not None and entry_px is not None and qty > 0:
                            active_side = side
                            active_contract = contract
                            active_opt = opt
                            active_qty = int(qty)
                            active_entry_px = float(entry_px)
                            active_origin = f"FORCE__{args.force_at}"
                            active_entry_ts = bar_t
                            melt_dist_max = None
                            did_force_entry = True
                            rsi1_reset_state()
                            rsi5_reset_state()
                            rsi5_on_entry(bar_t)
                    else:
                        print(f"[FORCE] SKIP already in position state={state_str(c)}")
                        did_force_entry = True
            except Exception as e:
                print(f"[FORCE][ERR] bad --force-at={getattr(args,'force_at',None)!r}: {e}")
                did_force_entry = True

        # 5m builder (unchanged)
        c5 = builder_5m.on_1m(bar_t, o, h, l, c, v1)
        if c5:
            row = {"t": norm_ts(c5.end), "o": float(c5.o), "h": float(c5.h), "l": float(c5.l), "c": float(c5.c)}
            df5 = df_append_row(df5, row, cols)

            if "t" in df5.columns:
                df5 = df5.reset_index(drop=True)
                df5["t"] = pd.to_datetime(df5["t"])
                df5 = df5.sort_values("t")
                df5 = df5.drop_duplicates(subset=["t"], keep="last")
                df5 = df5.set_index("t", drop=False)

            t5 = pd.Timestamp(row["t"])
            last_eval_t = state.get("last_5m_struct_eval_t")
            if last_eval_t != t5:
                state["last_5m_struct_eval_t"] = t5
                struct_evt = update_structure_5m(df5, state, left=2, right=2)
                if struct_evt:
                    print(f"[5m][STRUCT] {struct_evt['t']} {struct_evt['tag']} {struct_evt['kind']} px={struct_evt['px']:.2f}")
                else:
                    if len(df5) < 10:
                        print(f"[5m][STRUCT] warmup bars={len(df5)} (need pivots)")

            if len(df5) >= args.rsi_exit_len:
                rsi = RSIIndicator(df5["c"].astype(float), args.rsi_exit_len).rsi()
                df5["rsi"] = rsi
                val = rsi.iloc[-1]
                last_5m_rsi = float(val) if pd.notna(val) else last_5m_rsi

            print_5m_bar(c5, last_5m_rsi)

        # 15m dynamic (unchanged)
        c15 = builder_15m.on_1m(bar_t, o, h, l, c, v1)

        if builder_15m.curr_start:
            partial = Candle(
                norm_ts(builder_15m.curr_start),
                norm_ts(builder_15m.curr_end),
                float(builder_15m.o) if builder_15m.o is not None else o,
                float(builder_15m.h) if builder_15m.h is not None else h,
                float(builder_15m.l) if builder_15m.l is not None else l,
                float(builder_15m.c) if builder_15m.c is not None else c,
                float(builder_15m.v) if builder_15m.v is not None else 0.0,
            )

            dyn = compute_utbot_dynamic(df15, partial)
            if dyn:
                last_cstop_dyn = float(dyn["cstop"])
                new_atr = float(dyn["atr"]) if dyn.get("atr") is not None else None
                last_atr = new_atr if new_atr is not None else last_atr

        print(
            f"[1m] {bar_t} O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} "
            f"CSTOP:{f2(last_cstop)} "
            f"CS-D:{f2(last_cstop_dyn)} "
            f"RSI5:{f2(last_5m_rsi)} TRSI:{f2(last_tick_rsi)} RSI1:{f2(last_rsi_1m)} "
            f"state={state_str(c)}"
        )

        if active_side is not None:
            rsi5_arm_baseline_if_needed(bar_t)

        dyn_delta = None
        dist_to_dyn = None
        if last_cstop is not None and last_cstop_dyn is not None:
            dyn_delta = float(last_cstop_dyn) - float(last_cstop)
        if last_cstop_dyn is not None:
            dist_to_dyn = float(c) - float(last_cstop_dyn)

        print(
            f"[DYN] t={bar_t} Δdyn={f2(dyn_delta)} dist={f2(dist_to_dyn)} "
            f"dyn={f2(last_cstop_dyn)} cstop={f2(last_cstop)}"
        )

        # ─────────────────────────────────────────────
        # F22: RTH CARRY ENTRY (one-shot per day; fires only when FLAT)
        # ─────────────────────────────────────────────
        if bool(getattr(args, "rth_carry_entry", False)) and (active_side is None) and (not carry_used_today):
            if is_after_rth_end(bar_t):
                print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE t={bar_t} src=CARRY")
            else:
                entry_ok = bool(is_entry_time(bar_t, args.rth_entry_start, args)) and bool(is_rth_time(bar_t))

                regime = ut_regime or carry_seed_regime
                if regime is None and (last_cstop is not None):
                    regime = "BUY" if float(c) >= float(last_cstop) else "SELL"

                stop_ref = carry_stop_ref(regime, last_cstop, last_cstop_dyn)
                dist_pts = None
                dist_ok = False
                rsi_ok = False
                why = []

                if not entry_ok:
                    why.append("TIME")
                if regime not in ("BUY", "SELL"):
                    why.append("NO_REGIME")
                if last_atr is None or float(last_atr) <= 0:
                    why.append("NO_ATR")
                if stop_ref is None:
                    why.append("NO_STOP")
                if last_5m_rsi is None:
                    why.append("NO_RSI5")

                if (not why) and stop_ref is not None:
                    dist_pts = carry_dist_points(regime, float(c), float(stop_ref))
                    maxd = float(getattr(args, "carry_max_dist_atr", CARRY_MAX_DIST_ATR_DEFAULT)) * float(last_atr)
                    dist_ok = bool(dist_pts is not None and float(dist_pts) <= float(maxd) and float(dist_pts) >= 0.0)

                    rsi5 = float(last_5m_rsi)
                    if str(regime).upper() == "BUY":
                        rsi_ok = bool(rsi5 <= float(getattr(args, "carry_buy_max_rsi5", CARRY_BUY_MAX_RSI5_DEFAULT)))
                    else:
                        rsi_ok = bool(rsi5 >= float(getattr(args, "carry_sell_min_rsi5", CARRY_SELL_MIN_RSI5_DEFAULT)))

                    if not dist_ok:
                        why.append("DIST")
                    if not rsi_ok:
                        why.append("RSI")

                if bool(getattr(args, "carry_debug", False)) or (not rsi_ok) or (not dist_ok) or (not entry_ok):
                    try:
                        maxd_dbg = None
                        if last_atr is not None and float(last_atr) > 0:
                            maxd_dbg = float(getattr(args, "carry_max_dist_atr", CARRY_MAX_DIST_ATR_DEFAULT)) * float(last_atr)
                        print(
                            f"[CARRY][STAT] t={bar_t} entryOK={int(bool(entry_ok))} regime={regime} "
                            f"rsi5={f2(last_5m_rsi)} buyMax={float(getattr(args,'carry_buy_max_rsi5',CARRY_BUY_MAX_RSI5_DEFAULT)):.2f} "
                            f"sellMin={float(getattr(args,'carry_sell_min_rsi5',CARRY_SELL_MIN_RSI5_DEFAULT)):.2f} "
                            f"stopRef={f2(stop_ref)} dist={f2(dist_pts)} maxDist={f2(maxd_dbg)} atr={f2(last_atr)} "
                            f"rsiOK={int(bool(rsi_ok))} distOK={int(bool(dist_ok))} why={'+'.join(why) if why else 'OK'}"
                        )
                    except Exception:
                        pass

                if entry_ok and (not why) and rsi_ok and dist_ok and (regime in ("BUY", "SELL")):
                    side = "CALL" if regime == "BUY" else "PUT"
                    origin = f"UT15_CARRY__{regime}"
                    print(f"[CARRY][FIRE] t={bar_t} side={side} origin={origin} rsi5={f2(last_5m_rsi)} dist={f2(dist_pts)} atr={f2(last_atr)}")
                    contract, qty, entry_px, _oid, opt = await do_entry(side, bar1m, args, origin)
                    if contract is not None and entry_px is not None and qty > 0:
                        active_side = side
                        active_contract = contract
                        active_opt = opt
                        active_qty = int(qty)
                        active_entry_px = float(entry_px)
                        active_origin = origin
                        active_entry_ts = bar_t
                        melt_dist_max = None
                        carry_used_today = True
                        rsi1_reset_state()
                        rsi5_reset_state()
                        rsi5_on_entry(bar_t)

        # ─────────────────────────────────────────────
        # F19: LAST HOUR TREND ENGINE (ENTRY ONLY, separate)
        # ─────────────────────────────────────────────
        in_last_hour = bool(is_last_hour_ny(bar_t, start=LH_START, end=LH_END, tz=TZ_NY))
        if in_last_hour and (active_side is None):
            if is_after_rth_end(bar_t):
                print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE t={bar_t} src=LAST_HOUR_ENGINE")
            else:
                entry_ok = is_entry_time(bar_t, args.rth_entry_start, args)
                lh_act = process_last_hour_trend(
                    now=bar_t,
                    close_px=float(c),
                    last_cstop=last_cstop,
                    ut_regime=ut_regime,
                    stable_bars=int(ut_stable_bars),
                    min_stable_bars=int(LH_MIN_STABLE_BARS),
                    active_side=active_side,
                    entry_ok=bool(entry_ok),
                    allow_only_one=bool(LH_ALLOW_ONLY_ONE),
                    block_on_flip_bar=bool(LH_BLOCK_ON_FLIP_BAR),
                    confirmed_flip_now=bool(ut_flip_now),
                    lh=lh,
                )
                if lh_act and lh_act.get("type") == "ENTER":
                    contract, qty, entry_px, _oid, opt = await do_entry(
                        lh_act["side"], bar1m, args, lh_act["origin"]
                    )
                    if contract is not None and entry_px is not None and qty > 0:
                        active_side = lh_act["side"]
                        active_contract = contract
                        active_opt = opt
                        active_qty = int(qty)
                        active_entry_px = float(entry_px)
                        active_origin = lh_act["origin"]
                        active_entry_ts = bar_t
                        melt_dist_max = None
                        rsi1_reset_state()
                        rsi5_reset_state()
                        rsi5_on_entry(bar_t)
                        print(f"[LH][ENTRY] t={bar_t} side={active_side} origin={active_origin} reason={lh_act.get('reason')}")

        # ─────────────────────────────────────────────
        # EXIT ARB / RSI5 / RSI1 / CSTOP checks (logic preserved)
        # ─────────────────────────────────────────────
        rsi5_fired_hard = False
        rsi5_will_exit = False
        rsi5_delta = None
        rsi5_required = None
        drsi_why = "na"

        rsi1_level = None
        rsi1_fired = False
        rsi1_will_exit = False
        rsi1_allow_color = True
        rsi1_green = None

        cstop_breach = False

        dist_to_cstop = None
        dist_ratio = None
        cstop_intact = False
        melt_on = bool(getattr(args, "melt_hold", False))
        block_rsi5 = False
        block_rsi1 = False

        if active_side is not None and active_contract is not None and active_entry_px is not None:
            side = active_side

            if last_cstop is not None:
                if side == "CALL":
                    cstop_breach = bool(c <= float(last_cstop))
                else:
                    cstop_breach = bool(c >= float(last_cstop))

                dist_to_cstop = calc_cstop_distance(side, float(c), float(last_cstop))
                if melt_dist_max is None:
                    melt_dist_max = float(dist_to_cstop)
                else:
                    melt_dist_max = max(float(melt_dist_max), float(dist_to_cstop))

                if melt_dist_max is not None and float(melt_dist_max) > 0:
                    dist_ratio = float(dist_to_cstop) / float(melt_dist_max)

                dist_min = float(getattr(args, "melt_hold_dist_min", 0.0))
                ratio_min = float(getattr(args, "melt_hold_ratio_min", 0.0))

                cstop_intact = bool((not cstop_breach) and (dist_to_cstop is not None) and (float(dist_to_cstop) >= dist_min))

                if bool(getattr(args, "melt_hold_use_ratio", False)) and (dist_ratio is not None) and (ratio_min > 0):
                    cstop_intact = bool(cstop_intact and (float(dist_ratio) >= ratio_min))

            if (rsi5_base is not None) and (last_5m_rsi is not None):
                rsi5_delta = float(last_5m_rsi) - float(rsi5_base)

                if bool(getattr(args, "dyn_rsi_exit", False)):
                    rsi5_required = rsi5_elastic_threshold(rsi5_base, args)
                    ev = dyn_rsi5_eval(
                        side=side,
                        px_close=float(c),
                        base=rsi5_base,
                        rsi5=last_5m_rsi,
                        atr=last_atr,
                        cstop=last_cstop,
                        dyn=last_cstop_dyn,
                        dist_max=melt_dist_max,
                        args=args,
                    )
                    drsi_why = str(ev.get("why", "na"))
                    rsi5_fired_hard = bool(ev.get("fired", False))
                    rsi5_will_exit  = bool(ev.get("ok", False))
                    try:
                        print(
                            f"[DRSI] t={bar_t} side={side} base={f2(rsi5_base)} rsi5={f2(last_5m_rsi)} "
                            f"Δ={('na' if rsi5_delta is None else f'{rsi5_delta:+.2f}')} req={f2(rsi5_required)} "
                            f"fired={int(rsi5_fired_hard)} ok={int(rsi5_will_exit)} why={drsi_why} "
                            f"distNear={f2(ev.get('dist_near'))} prox={f2(ev.get('prox'))} "
                            f"shrink={f2(ev.get('shrink'))}/{f2(ev.get('shrink_req'))}"
                        )
                    except Exception:
                        pass
                else:
                    hard = float(args.rsi_exit_thresh)
                    rsi5_required = hard
                    if side == "CALL":
                        rsi5_fired_hard = bool(rsi5_delta <= -hard)
                    else:
                        rsi5_fired_hard = bool(rsi5_delta >= +hard)
                    rsi5_will_exit = bool(rsi5_fired_hard)

            if (not args.no_rsi1_step) and (last_rsi_1m is not None):
                rsi1 = float(last_rsi_1m)

                rsi1_green = (c >= o) if side == "CALL" else (c <= o)
                rsi1_allow_color = True
                if args.rsi1_green_only and (not args.rsi1_allow_red):
                    rsi1_allow_color = bool(rsi1_green)

                if side == "CALL":
                    if (rsi1_extreme is None) or (rsi1 > float(rsi1_extreme)):
                        rsi1_extreme = float(rsi1)
                        rsi1_extreme_ts = bar_t
                    rsi1_level = (float(rsi1_extreme) - float(args.rsi1_step)) if rsi1_extreme is not None else None
                    rsi1_fired = bool(rsi1_level is not None and rsi1 <= float(rsi1_level))
                else:
                    if (rsi1_extreme is None) or (rsi1 < float(rsi1_extreme)):
                        rsi1_extreme = float(rsi1)
                        rsi1_extreme_ts = bar_t
                    rsi1_level = (float(rsi1_extreme) + float(args.rsi1_step)) if rsi1_extreme is not None else None
                    rsi1_fired = bool(rsi1_level is not None and rsi1 >= float(rsi1_level))

                if (not rsi1_armed) and (rsi1_extreme_ts is not None):
                    mins = (bar_t - rsi1_extreme_ts).total_seconds() / 60.0
                    if mins >= float(args.rsi1_arm_mins):
                        rsi1_armed = True

                rsi1_will_exit = bool(rsi1_armed and rsi1_fired and rsi1_allow_color)

            block_rsi5 = bool(melt_on and cstop_intact)
            block_rsi1 = bool(melt_on and cstop_intact)

            winner = "NONE"
            if cstop_breach:
                winner = "CSTOP"
            elif rsi5_will_exit and (not block_rsi5):
                winner = "RSI5"
            elif rsi1_will_exit and (not block_rsi1):
                winner = "RSI1(shadow)" if (not args.rsi1_exit) else "RSI1"

            print(
                f"[RSI5][STAT] t={bar_t} base={f2(rsi5_base)}"
                f"{' (pending)' if rsi5_base_pending else ''} rsi5={f2(last_5m_rsi)} "
                f"Δ={('na' if rsi5_delta is None else f'{rsi5_delta:+.2f}')} "
                f"hard={float(args.rsi_exit_thresh):.2f} fired={int(rsi5_fired_hard)} "
                f"mode={'REAL' if args.rsi5_exit else 'SHADOW'} "
                f"{'dyn=ON' if bool(getattr(args,'dyn_rsi_exit',False)) else 'dyn=OFF'} "
                f"req={f2(rsi5_required)} ok={int(bool(rsi5_will_exit))} why={drsi_why}"
            )

            print(
                f"[RSI1][STAT] t={bar_t} side={side} rsi1={f2(last_rsi_1m)} "
                f"ext={f2(rsi1_extreme)}@{rsi1_extreme_ts} lvl={f2(rsi1_level)} "
                f"arm={int(rsi1_armed)} fired={int(rsi1_fired)} "
                f"green={('na' if rsi1_green is None else int(bool(rsi1_green)))} "
                f"allow={int(bool(rsi1_allow_color))} WX={int(bool(rsi1_will_exit))} "
                f"mode={'REAL' if args.rsi1_exit else 'SHADOW'}"
            )

            print(
                f"[EXIT-ARB] t={bar_t} side={side} px={c:.2f} "
                f"RSI5Δ={('na' if rsi5_delta is None else f'{rsi5_delta:+.2f}')}/WX={int(bool(rsi5_will_exit))} "
                f"RSI1lvl={f2(rsi1_level)}/WX={int(bool(rsi1_will_exit))} "
                f"CSTOP={f2(last_cstop)}/br={int(bool(cstop_breach))} "
                f"WIN={winner}"
            )

            print(
                f"[MELT] t={bar_t} on={int(melt_on)} dist={f2(dist_to_cstop)} "
                f"distMax={f2(melt_dist_max)} ratio={f2(dist_ratio)} intact={int(bool(cstop_intact))} "
                f"block5={int(block_rsi5)} block1={int(block_rsi1)}"
            )

            if (rsi5_will_exit and block_rsi5) or (rsi1_will_exit and block_rsi1):
                print(
                    f"[RSI-EXIT-CAND] t={bar_t} side={side} px={c:.2f} "
                    f"RSI5Δ={('na' if rsi5_delta is None else f'{rsi5_delta:+.2f}')} fired5={int(bool(rsi5_fired_hard))} "
                    f"RSI5ok={int(bool(rsi5_will_exit))} why={drsi_why} "
                    f"RSI1wx={int(bool(rsi1_will_exit))} "
                    f"dist={f2(dist_to_cstop)} distMax={f2(melt_dist_max)} ratio={f2(dist_ratio)} "
                    f"-> HOLD (melt_hold)"
                )

        # ─────────────────────────────────────────────
        # RSI5 exit (F19: arm continuation via engine helper)
        # ─────────────────────────────────────────────
        if active_side is not None and active_contract is not None and active_entry_px is not None:
            if bool(getattr(args, "dyn_rsi_exit", False)):
                should_exit = bool(rsi5_will_exit)
                reason_tag = f"RSI5_DYN_EXIT[{drsi_why}]"
            else:
                should_exit = bool(rsi5_fired_hard)
                reason_tag = "RSI5_SETBACK_EXIT"

            if should_exit:
                if bool(getattr(args, "melt_hold", False)) and bool(cstop_intact):
                    print("[RSI5][BLOCK] reason=melt_hold_cstop_intact")
                elif args.rsi5_exit:
                    ok = await do_exit(
                        args, active_contract, active_qty, active_entry_px, active_side,
                        bar1m, reason_tag, active_origin or "UNK", active_opt
                    )
                    if ok:
                        if bool(getattr(args, "cont1_after_dyn_exit", False)) and (not cont.used_today) and str(reason_tag).startswith("RSI5_DYN_EXIT"):
                            cont_arm_after_dyn_exit(
                                cont=cont,
                                side=str(active_side).upper(),
                                now=bar_t,
                                reason_tag=str(reason_tag),
                                origin_hint=str(active_origin or "UNK"),
                                cooldown_mins=float(getattr(args, "cont1_cooldown_mins", 3.0)),
                                debug=bool(getattr(args, "cont1_debug", False)),
                            )

                        active_side = None
                        active_contract = None
                        active_opt = None
                        active_entry_px = None
                        active_origin = None
                        active_entry_ts = None
                        active_qty = 1
                        melt_dist_max = None
                        rsi1_reset_state()
                        rsi5_reset_state()
                        return
                else:
                    print("[RSI5][NOEXIT] reason=print_only")

        # RSI1 exit (unchanged)
        if (not args.no_rsi1_step) and active_side is not None and active_contract is not None and active_entry_px is not None:
            if rsi1_will_exit:
                if bool(getattr(args, "melt_hold", False)) and bool(cstop_intact):
                    print("[RSI1][BLOCK] reason=melt_hold_cstop_intact")
                elif args.rsi1_exit:
                    ok = await do_exit(
                        args, active_contract, active_qty, active_entry_px, active_side,
                        bar1m, "RSI1_STEPBACK_EXIT", active_origin or "UNK", active_opt
                    )
                    if ok:
                        active_side = None
                        active_contract = None
                        active_opt = None
                        active_entry_px = None
                        active_origin = None
                        active_entry_ts = None
                        active_qty = 1
                        melt_dist_max = None
                        rsi1_reset_state()
                        rsi5_reset_state()
                        return
                else:
                    print("[RSI1][NOEXIT] reason=print_only")

        # EOD flatten (unchanged)
        if active_side is not None and active_contract is not None and active_entry_px is not None:
            if is_eod_flatten_window(bar_t):
                ok = await do_exit(
                    args, active_contract, active_qty, active_entry_px, active_side,
                    bar1m, "EOD_1559", active_origin or "UNK", active_opt
                )
                if ok:
                    active_side = None
                    active_contract = None
                    active_opt = None
                    active_entry_px = None
                    active_origin = None
                    active_entry_ts = None
                    active_qty = 1
                    melt_dist_max = None
                    rsi1_reset_state()
                    rsi5_reset_state()
                return

        # ─────────────────────────────────────────────
        # F19: CONTINUATION ENGINE (fires only when FLAT)
        # ─────────────────────────────────────────────
        act = process_continuation(
            now=bar_t,
            close_px=float(c),
            last_cstop=last_cstop,
            last_confirmed_ut_flip=last_confirmed_ut_flip,
            active_side=active_side,
            cont1_after_dyn_exit=bool(getattr(args, "cont1_after_dyn_exit", False)),
            cont1_ut_buffer=float(getattr(args, "cont1_ut_buffer", 0.0)),
            cont1_debug=bool(getattr(args, "cont1_debug", False)),
            cont=cont,
        )
        if act and act.get("type") == "ENTER":
            if is_after_rth_end(bar_t):
                print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE t={bar_t} src=CONT1 origin={act.get('origin')}")
            else:
                contract, qty, entry_px, _oid, opt = await do_entry(
                    act["side"],
                    bar1m,
                    args,
                    act["origin"],
                    bypass_entry_window=False,
                )
                if contract is not None and entry_px is not None and qty > 0:
                    active_side = act["side"]
                    active_contract = contract
                    active_opt = opt
                    active_qty = int(qty)
                    active_entry_px = float(entry_px)
                    active_origin = act["origin"]
                    active_entry_ts = bar_t
                    melt_dist_max = None
                    rsi1_reset_state()
                    rsi5_reset_state()
                    rsi5_on_entry(bar_t)

                    cont.pending = False
                    cont.used_today = True
                    if bool(getattr(args, "cont1_debug", False)):
                        print(f"[CONT1][FIRE] t={bar_t} side={active_side} contract={active_contract} entry={active_entry_px:.2f} origin={active_origin}")

        analyze_wick(bar1m, active_side)

        # CONFIRMED 15m close
        if c15:
            row = {"t": norm_ts(c15.end), "o": float(c15.o), "h": float(c15.h), "l": float(c15.l), "c": float(c15.c)}
            df15 = df_append_row(df15, row, cols)

            new_evs = ms15.update(df15)
            for ev in new_evs:
                print_pivot_tape(ev, now_px=float(c15.c), tape=pivot_tape)

            sig = compute_utbot_signal(df15)
            if sig:
                last_cstop = float(sig["cstop"])
                last_atr   = float(sig["atr"])

                ut_flip_now = False
                if bool(sig.get("buy")):
                    last_confirmed_ut_flip = "BUY"
                    ut_regime = "BUY"
                    ut_flip_now = True
                elif bool(sig.get("sell")):
                    last_confirmed_ut_flip = "SELL"
                    ut_regime = "SELL"
                    ut_flip_now = True

                if ut_flip_now:
                    ut_stable_bars = 1
                else:
                    if ut_regime in ("BUY", "SELL"):
                        ut_stable_bars += 1

                print_15m_bar(
                    c15,
                    cstop=last_cstop,
                    atr=last_atr,
                    buy=bool(sig.get("buy")),
                    sell=bool(sig.get("sell")),
                )

                if int(args.dump15) > 0:
                    dump_last_15m(df15, n=int(args.dump15), atr_period=ATR_PERIOD)

                on_confirmed_ut_flip_maybe_cancel_cont1(
                    cont=cont,
                    cont1_debug=bool(getattr(args, "cont1_debug", False)),
                    now=norm_ts(c15.end),
                    cont_side=cont.side,
                    sig_buy=bool(sig.get("buy")),
                    sig_sell=bool(sig.get("sell")),
                )

                # ─────────────────────────────────────────────
                # F13: FIRST-HOUR FILTER (CONFIRMED 15m flips ONLY) (unchanged)
                # ─────────────────────────────────────────────
                allow_side: Optional[Side] = None
                reason: str = "no_filter"

                t15 = norm_ts(c15.end)
                raw_flip: Optional[Side] = None
                if bool(sig.get("buy")):
                    raw_flip = "BUY"
                elif bool(sig.get("sell")):
                    raw_flip = "SELL"

                if fh_filter is not None and hasattr(fh_filter, "maybe_release_candidate"):
                    rel = fh_filter.maybe_release_candidate(t15)
                    if rel and rel.get("allow", False):
                        allow_side = _side_ok(rel["side"])
                        reason = str(rel.get("reason", "released"))
                        print(f"[FH] RELEASE @ {t15} side={allow_side} reason={reason}")

                if fh_filter is not None and raw_flip is not None:
                    info = fh_filter.update_flip(t15, _side_ok(raw_flip))
                    if not info.get("allow", False):
                        print(f"[FH] SUPPRESS @ {t15} side={raw_flip} reason={info.get('reason')}")
                        allow_side = None
                    else:
                        allow_side = _side_ok(info["side"])
                        reason = str(info.get("reason", "allowed"))
                        print(f"[FH] ALLOW @ {t15} side={allow_side} reason={reason}")

                if fh_filter is None and raw_flip is not None:
                    allow_side = _side_ok(raw_flip)
                    reason = "pass_no_filter"
                    print(f"[FH] PASS @ {t15} side={allow_side} reason={reason}")

                # CONFIRMED entries (F21+: block at/after close)
                if allow_side == "BUY" and active_side is None and args.entry_mode in ("confirmed", "hybrid"):
                    if is_after_rth_end(bar_t) or is_after_rth_end(t15):
                        print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE t15={t15} t1={bar_t} side=BUY src=UT15_CONF")
                    else:
                        contract, qty, entry_px, _oid, opt = await do_entry("CALL", bar1m, args, f"UT15_CONF__{reason}")
                        if contract is not None and entry_px is not None and qty > 0:
                            active_side = "CALL"
                            active_contract = contract
                            active_opt = opt
                            active_qty = int(qty)
                            active_entry_px = float(entry_px)
                            active_origin = f"UT15_CONF__{reason}"
                            active_entry_ts = bar_t
                            melt_dist_max = None
                            rsi1_reset_state()
                            rsi5_reset_state()
                            rsi5_on_entry(bar_t)
                            print(f"[UT-CONF-TRIGGER] {fmt_ts(c15.end)} side=BUY c={float(c15.c):.2f} cstop={float(last_cstop):.2f} FH={reason}")

                if allow_side == "SELL" and active_side is None and args.entry_mode in ("confirmed", "hybrid"):
                    if is_after_rth_end(bar_t) or is_after_rth_end(t15):
                        print(f"[RTH-BLOCK] skip_entry reason=AFTER_CLOSE t15={t15} t1={bar_t} side=SELL src=UT15_CONF")
                    else:
                        contract, qty, entry_px, _oid, opt = await do_entry("PUT", bar1m, args, f"UT15_CONF__{reason}")
                        if contract is not None and entry_px is not None and qty > 0:
                            active_side = "PUT"
                            active_contract = contract
                            active_opt = opt
                            active_qty = int(qty)
                            active_entry_px = float(entry_px)
                            active_origin = f"UT15_CONF__{reason}"
                            active_entry_ts = bar_t
                            melt_dist_max = None
                            rsi1_reset_state()
                            rsi5_reset_state()
                            rsi5_on_entry(bar_t)
                            print(f"[UT-CONF-TRIGGER] {fmt_ts(c15.end)} side=SELL c={float(c15.c):.2f} cstop={float(last_cstop):.2f} FH={reason}")

    stream.subscribe_bars(on_bar, args.symbol)
    await stream._run_forever()


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    asyncio.run(run_live(args))



