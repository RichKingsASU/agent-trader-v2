#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zzz-utbot_atr_live_1M_Rev_F22.py

Refactor scope (per integration request):
- KEEP ONLY: indicator calculations + signal/decision logic
- REMOVE/DISABLE: any market-data ingestion (websocket/REST polling), feed startup, CLI main loops
- NO env access at import time
- NO execution side effects (no order placement, no intent emission)

This module is now a pure, dataframe-driven strategy evaluator. It can be called by
an execution engine that loads candles from DB (or provides a dataframe) and then
consumes the returned signals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Literal, Optional, Tuple, TYPE_CHECKING, TypedDict

try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd


# ─────────────────────────────────────────────────────────────
# TIME CONSTANTS (preserved semantics)
# ─────────────────────────────────────────────────────────────

_TZ_NY_NAME = "America/New_York"
_TZ_UTC_NAME = "UTC"


def _tz_ny():
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(_TZ_NY_NAME)
    except Exception:  # pragma: no cover
        return None


def _tz_utc():
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(_TZ_UTC_NAME)
    except Exception:  # pragma: no cover
        return None

RTH_TRADE_START = dtime(9, 30)
RTH_TRADE_END = dtime(16, 0)  # end is EXCLUSIVE for entries (F21+)

EOD_WINDOW_START = dtime(15, 58)
EOD_WINDOW_END = dtime(16, 0)


# ─────────────────────────────────────────────────────────────
# CONFIG + SIGNAL TYPES
# ─────────────────────────────────────────────────────────────


class UtbotF22Config:
    """
    Lightweight runtime config object (no dataclass to keep import-by-path robust).
    """

    def __init__(
        self,
        *,
        atr_period: int = 10,
        rsi_len_5m: int = 14,
        tf_5m: str = "5min",
        tf_15m: str = "15min",
        first_hour_filter: Literal["none", "window", "consec2"] = "window",
        first_hour_minutes: int = 60,
        first_hour_window_minutes: int = 45,
        block_entries_after_rth_end: bool = True,
    ) -> None:
        self.atr_period = int(atr_period)
        self.rsi_len_5m = int(rsi_len_5m)
        self.tf_5m = str(tf_5m)
        self.tf_15m = str(tf_15m)
        self.first_hour_filter = first_hour_filter
        self.first_hour_minutes = int(first_hour_minutes)
        self.first_hour_window_minutes = int(first_hour_window_minutes)
        self.block_entries_after_rth_end = bool(block_entries_after_rth_end)


SignalKind = Literal["ENTER", "EXIT"]
SignalSide = Literal["CALL", "PUT"]
SignalOrigin = Literal["UT15_CONF", "EOD_FLATTEN"]


class StrategySignal(TypedDict):
    ts: datetime
    kind: SignalKind
    side: Optional[SignalSide]  # ENTER signals have side; EXIT typically side=None (close position)
    origin: SignalOrigin
    reason: str
    indicators: Dict[str, Any]


# ─────────────────────────────────────────────────────────────
# FIRST-HOUR FILTER (confirmed 15m flips only)  (F13 baseline)
# ─────────────────────────────────────────────────────────────

Side = Literal["BUY", "SELL"]


def _side_ok(side: str) -> Side:
    s = str(side).upper().strip()
    if s not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got: {side!r}")
    return s  # type: ignore[return-value]


class FlipEvent:
    __slots__ = ("t", "side")

    def __init__(self, *, t: datetime, side: Side) -> None:
        self.t = t
        self.side = side


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

    def reset_day(self) -> None:
        self._candidate = None

    def _rth0(self, t: datetime) -> datetime:
        return datetime(
            t.year,
            t.month,
            t.day,
            self.rth_start.hour,
            self.rth_start.minute,
            self.rth_start.second,
            tzinfo=t.tzinfo,
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

    def reset_day(self) -> None:
        self._candidate_side = None

    def _rth0(self, t: datetime) -> datetime:
        return datetime(
            t.year,
            t.month,
            t.day,
            self.rth_start.hour,
            self.rth_start.minute,
            self.rth_start.second,
            tzinfo=t.tzinfo,
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
# TIME GUARDS
# ─────────────────────────────────────────────────────────────


def _require_tz(ts: datetime) -> datetime:
    if ts.tzinfo is not None:
        return ts
    # default to UTC if naive (caller may pass naive DB timestamps)
    return ts.replace(tzinfo=_tz_utc())


def is_eod_flatten_window(ts: datetime) -> bool:
    tz_ny = _tz_ny()
    if tz_ny is None:
        return False
    t = _require_tz(ts).astimezone(tz_ny).time()
    return (t >= EOD_WINDOW_START) and (t <= EOD_WINDOW_END)


def is_rth_time(ts: datetime) -> bool:
    """
    RTH is [09:30, 16:00) for trading logic.
    """
    tz_ny = _tz_ny()
    if tz_ny is None:
        return False
    t = _require_tz(ts).astimezone(tz_ny).time()
    return (t >= RTH_TRADE_START) and (t < RTH_TRADE_END)


def is_after_rth_end(ts: datetime) -> bool:
    tz_ny = _tz_ny()
    if tz_ny is None:
        return False
    t = _require_tz(ts).astimezone(tz_ny).time()
    return t >= RTH_TRADE_END


# ─────────────────────────────────────────────────────────────
# INDICATORS (no external ta dependency)
# ─────────────────────────────────────────────────────────────


def _rma(series, length: int):
    """
    Wilder's RMA (smoothed moving average), used for RSI.
    """
    series = series.astype(float)
    alpha = 1.0 / float(length)
    return series.ewm(alpha=alpha, adjust=False).mean()


def compute_rsi(close, length: int):
    close = close.astype(float)
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = _rma(up, length)
    avg_down = _rma(down, length)
    rs = avg_up / avg_down.replace(0.0, float("nan"))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_atr(df_ohlc, period: int):
    h = df_ohlc["h"].astype(float)
    l = df_ohlc["l"].astype(float)
    c = df_ohlc["c"].astype(float)
    prev_c = c.shift(1)
    tr = (h - l).to_frame("hl")
    tr["hc"] = (h - prev_c).abs()
    tr["lc"] = (l - prev_c).abs()
    true_range = tr.max(axis=1)
    return _rma(true_range, int(period))


def compute_ut_trailing_stop(df15, *, atr_period: int) -> "pd.DataFrame":
    """
    UTBot-style ATR trailing stop on 15m bars.

    Returns a copy with:
      - ATR
      - CSTOP (trailing stop)
      - buy / sell flip booleans (confirmed on bar close)
    """
    import pandas as pd  # local import: avoid import-time dependency

    if df15 is None or df15.empty:
        return pd.DataFrame(columns=list(df15.columns) if df15 is not None else [])

    out = df15.sort_values("t").reset_index(drop=True).copy()
    out["ATR"] = compute_atr(out, period=int(atr_period))

    c = out["c"].astype(float)
    atr = out["ATR"].astype(float)

    stop = pd.Series(index=out.index, dtype="float64")
    for i in range(len(out)):
        if i == 0:
            stop.iloc[i] = float(c.iloc[i]) - float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else float(c.iloc[i])
            continue

        prev_stop = float(stop.iloc[i - 1])
        prev_close = float(c.iloc[i - 1])
        this_close = float(c.iloc[i])

        if pd.isna(atr.iloc[i]):
            stop.iloc[i] = prev_stop
            continue

        # This is the same state machine as the prior `compute_ut_snapshot` implementation:
        if this_close > prev_stop and prev_close > prev_stop:
            stop.iloc[i] = max(prev_stop, this_close - float(atr.iloc[i]))
        elif this_close < prev_stop and prev_close < prev_stop:
            stop.iloc[i] = min(prev_stop, this_close + float(atr.iloc[i]))
        else:
            stop.iloc[i] = (this_close - float(atr.iloc[i])) if this_close > prev_stop else (this_close + float(atr.iloc[i]))

    out["CSTOP"] = stop
    out["buy"] = (c > out["CSTOP"].astype(float)) & (c.shift(1) <= out["CSTOP"].shift(1).astype(float))
    out["sell"] = (c < out["CSTOP"].astype(float)) & (c.shift(1) >= out["CSTOP"].shift(1).astype(float))
    return out


# ─────────────────────────────────────────────────────────────
# DATAFRAME NORMALIZATION / RESAMPLING
# ─────────────────────────────────────────────────────────────


def _as_utc_ts_index(df: "pd.DataFrame") -> "pd.DataFrame":
    import pandas as pd  # local import

    if df is None or df.empty:
        return df

    out = df.copy()
    if "t" in out.columns:
        out["t"] = pd.to_datetime(out["t"], utc=True, errors="coerce")
        out = out.dropna(subset=["t"]).sort_values("t")
        out = out.set_index("t", drop=False)
        return out

    # If caller already set datetime index:
    idx = out.index
    if isinstance(idx, pd.DatetimeIndex):
        if idx.tz is None:
            out.index = idx.tz_localize("UTC")
        else:
            out.index = idx.tz_convert("UTC")
        out = out.sort_index()
        if "t" not in out.columns:
            out["t"] = out.index
        return out

    raise ValueError("df must have a datetime column 't' or a DatetimeIndex")


def _resample_ohlcv(df_1m: "pd.DataFrame", rule: str) -> "pd.DataFrame":
    """
    Resample OHLCV to `rule` using right-closed, right-labeled bars.
    """
    import pandas as pd  # local import

    df = _as_utc_ts_index(df_1m)
    if df is None or df.empty:
        return pd.DataFrame(columns=["t", "o", "h", "l", "c", "v"])

    agg = {
        "o": "first",
        "h": "max",
        "l": "min",
        "c": "last",
    }
    if "v" in df.columns:
        agg["v"] = "sum"

    out = df.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["o", "h", "l", "c"])
    out["t"] = out.index
    if "v" not in out.columns:
        out["v"] = 0.0
    return out.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# STRATEGY EVALUATION API (pure; no feed; no execution)
# ─────────────────────────────────────────────────────────────


def _build_first_hour_filter(cfg: UtbotF22Config):
    if cfg.first_hour_filter == "none":
        return None
    if cfg.first_hour_filter == "window":
        return FirstHourWindowSuppressor(
            rth_start=RTH_TRADE_START,
            first_hour_minutes=int(cfg.first_hour_minutes),
            window_minutes=int(cfg.first_hour_window_minutes),
        )
    return FirstHourConsec2Filter(rth_start=RTH_TRADE_START, first_hour_minutes=int(cfg.first_hour_minutes))


def generate_signals(
    df_1m: "pd.DataFrame",
    *,
    config: Optional[UtbotF22Config] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Tuple[List[StrategySignal], Dict[str, Any]]:
    """
    Evaluate UTBot-style 15m flips from a provided 1m dataframe.

    Inputs:
    - df_1m: must contain columns: t,o,h,l,c (v optional). `t` may be tz-aware or naive.
    - state: optional mutable state (position + first-hour filter); will be copied and returned.

    Output:
    - signals: list of StrategySignal (ENTER/EXIT)
    - next_state: dict to persist between calls
    """
    import pandas as pd  # local import

    cfg = config or UtbotF22Config()
    st: Dict[str, Any] = dict(state or {})
    signals: List[StrategySignal] = []

    df_1m = _as_utc_ts_index(df_1m)
    if df_1m is None or df_1m.empty:
        return [], st

    # Resample to 5m + 15m for indicators
    df5 = _resample_ohlcv(df_1m, cfg.tf_5m)
    df15 = _resample_ohlcv(df_1m, cfg.tf_15m)

    # 5m RSI (exposed via indicators; not used to force exits here)
    if not df5.empty and int(cfg.rsi_len_5m) > 1:
        df5["RSI5"] = compute_rsi(df5["c"], int(cfg.rsi_len_5m))

    # 15m UT trailing stop + confirmed flips
    ut = compute_ut_trailing_stop(df15, atr_period=int(cfg.atr_period))
    if ut.empty:
        return [], st

    # Position state is intentionally minimal (no execution side effects):
    # - "active": bool
    # - "active_side": CALL|PUT (set on ENTER; cleared on EXIT)
    active = bool(st.get("active", False))
    active_side: Optional[SignalSide] = st.get("active_side")

    fh = st.get("_fh_filter")
    if fh is None:
        fh = _build_first_hour_filter(cfg)
        if fh is not None:
            fh.reset_day()
        st["_fh_filter"] = fh

    for i, row in ut.iterrows():
        t15 = pd.Timestamp(row["t"]).to_pydatetime()
        ts = _require_tz(t15)
        tz_ny = _tz_ny()
        if tz_ny is not None:
            ts = ts.astimezone(tz_ny)

        # EOD flatten signal (strategy decision only)
        if active and is_eod_flatten_window(ts):
            signals.append(
                {
                    "ts": ts,
                    "kind": "EXIT",
                    "side": None,
                    "origin": "EOD_FLATTEN",
                    "reason": "EOD_1559",
                    "indicators": {
                        "c": float(row["c"]),
                        "cstop": float(row["CSTOP"]) if row.get("CSTOP") is not None else None,
                        "atr": float(row["ATR"]) if row.get("ATR") is not None else None,
                    },
                }
            )
            active = False
            active_side = None
            continue

        raw_flip: Optional[Side] = None
        if bool(row.get("buy", False)):
            raw_flip = "BUY"
        elif bool(row.get("sell", False)):
            raw_flip = "SELL"

        if raw_flip is None:
            continue

        # Apply first-hour filter (confirmed flips only)
        allow_side: Optional[Side] = None
        reason = "pass_no_filter"

        if fh is not None and hasattr(fh, "maybe_release_candidate"):
            rel = fh.maybe_release_candidate(ts)
            if rel and rel.get("allow", False):
                allow_side = _side_ok(rel["side"])
                reason = str(rel.get("reason", "released"))

        if fh is not None:
            info = fh.update_flip(ts, _side_ok(raw_flip))
            if info.get("allow", False):
                allow_side = _side_ok(info["side"])
                reason = str(info.get("reason", "allowed"))
            else:
                allow_side = None
        else:
            allow_side = _side_ok(raw_flip)

        if allow_side is None:
            continue

        # Entry policy: only enter when flat; block after RTH close if requested
        if (not active) and cfg.block_entries_after_rth_end and is_after_rth_end(ts):
            continue

        if not active:
            side: SignalSide = "CALL" if allow_side == "BUY" else "PUT"
            signals.append(
                {
                    "ts": ts,
                    "kind": "ENTER",
                    "side": side,
                    "origin": "UT15_CONF",
                    "reason": f"{allow_side} ({reason})",
                    "indicators": {
                        "c": float(row["c"]),
                        "cstop": float(row["CSTOP"]) if row.get("CSTOP") is not None else None,
                        "atr": float(row["ATR"]) if row.get("ATR") is not None else None,
                        "ut_buy": bool(row.get("buy", False)),
                        "ut_sell": bool(row.get("sell", False)),
                    },
                }
            )
            active = True
            active_side = side
            continue

        # If already active, ignore entry flips (this file no longer handles intrabar exits/flip-to-reverse).
        # The execution engine can choose how to interpret overlapping signals.

    st["active"] = bool(active)
    st["active_side"] = active_side
    return signals, st


def evaluate_from_prebuilt_timeframes(
    *,
    df5: "pd.DataFrame",
    df15: "pd.DataFrame",
    config: Optional[UtbotF22Config] = None,
) -> Dict[str, "pd.DataFrame"]:
    """
    Utility for engines that already load/calculate higher timeframes from DB.
    Returns the enriched indicator frames (RSI5 + UT stop/flip series).
    """
    cfg = config or UtbotF22Config()
    out: Dict[str, "pd.DataFrame"] = {}

    if df5 is not None and not df5.empty:
        d5 = df5.sort_values("t").reset_index(drop=True).copy()
        d5["RSI5"] = compute_rsi(d5["c"], int(cfg.rsi_len_5m))
        out["5m"] = d5
    else:
        out["5m"] = df5

    out["15m"] = compute_ut_trailing_stop(df15, atr_period=int(cfg.atr_period))
    return out


def is_execution_enabled(*, env: Optional[Dict[str, str]] = None) -> bool:
    """
    Repo-level execution guard.

    This module never performs execution side effects, but downstream callers can use
    this guard to decide whether to *act* on returned signals.
    """
    import os

    e = env if env is not None else os.environ  # type: ignore[assignment]
    v = e.get("EXECUTION_ENABLED")
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "on"}

