"""
Volatility / Breakout Strategy (enterprise-normalized).

Design goals (per request):
- Explicit volatility measures: ATR (primary), realized vol (secondary), IV (optional input).
- Clear breakout definition with entry/exit symmetry (Donchian channel cross).
- Guardrails:
  - Time-based exit (configurable, defaults before close window)
  - Max notional per signal (expressed via confidence/allocation_pct clamp)
  - HOLD during market-close window (no new risk; avoids illiquidity/MOC)
- Output: TradingSignal ONLY (no dicts, no AgentIntent).

Important integration note:
This strategy is compatible with the repo's `functions/strategies/base_strategy.py`
framework (sync BaseStrategy returning `TradingSignal`).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, time as dtime
from math import log, sqrt
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

import pytz

from .base_strategy import BaseStrategy, SignalType, TradingSignal

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Safety hardening (execution intent suppression) – same policy as GammaScalper.
# -----------------------------------------------------------------------------

def _execution_intent_allowed() -> tuple[bool, str, Dict[str, str]]:
    trading_mode = (os.getenv("TRADING_MODE") or "").strip()
    execution_halted = (os.getenv("EXECUTION_HALTED") or "").strip()
    enable_dangerous = (os.getenv("ENABLE_DANGEROUS_FUNCTIONS") or "").strip()
    exec_guard_unlock = (os.getenv("EXEC_GUARD_UNLOCK") or "").strip()

    env_snapshot = {
        "TRADING_MODE": trading_mode,
        "EXECUTION_HALTED": execution_halted,
        "ENABLE_DANGEROUS_FUNCTIONS": enable_dangerous,
        "EXEC_GUARD_UNLOCK": exec_guard_unlock,
    }

    if trading_mode.lower() != "paper":
        return False, "TRADING_MODE must be 'paper'", env_snapshot

    if execution_halted.lower() in {"1", "true", "t", "yes", "y", "on"}:
        return False, "EXECUTION_HALTED is active (kill switch)", env_snapshot

    if enable_dangerous != "true":
        return False, "ENABLE_DANGEROUS_FUNCTIONS must equal 'true'", env_snapshot
    if exec_guard_unlock != "1":
        return False, "EXEC_GUARD_UNLOCK must equal '1'", env_snapshot

    return True, "ok", env_snapshot


@dataclass(frozen=True)
class _VolMeasures:
    atr: Optional[float]
    realized_vol: Optional[float]
    implied_vol: Optional[float]


def _parse_iso_ts(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        s = str(ts).strip()
        if not s:
            return None
        # Handle Zulu "Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _ny_time(ts: Optional[datetime], tz_ny) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        # Assume UTC if timezone missing (fail-closed, deterministic)
        ts = ts.replace(tzinfo=pytz.UTC)
    return ts.astimezone(tz_ny)


def _parse_hhmm(value: str, *, default: dtime) -> dtime:
    try:
        s = str(value).strip()
        if not s:
            return default
        hh, mm = s.split(":")
        return dtime(int(hh), int(mm), 0)
    except Exception:
        return default


def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        if isinstance(x, bool):
            return None
        return float(x)
    except Exception:
        return None


def _extract_bars(market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract an OHLCV bar list from market_data.

    Supported shapes:
    - market_data["bars"] or ["history"] or ["ohlcv"] -> list[dict] with {open,high,low,close}
    """
    for k in ("bars", "history", "ohlcv", "recent_bars"):
        v = market_data.get(k)
        if isinstance(v, list):
            # Best-effort filter: only dict bars
            out = [b for b in v if isinstance(b, dict)]
            if out:
                return out
    # No history provided; return empty list
    return []


def _bar_ohlc(bar: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    o = _as_float(bar.get("open", bar.get("o")))
    h = _as_float(bar.get("high", bar.get("h")))
    l = _as_float(bar.get("low", bar.get("l")))
    c = _as_float(bar.get("close", bar.get("c", bar.get("price"))))
    return o, h, l, c


def _compute_atr(bars: List[Dict[str, Any]], period: int) -> Optional[float]:
    """
    Compute ATR using True Range over the last `period` completed bars.

    To avoid lookahead, ATR uses bars excluding the latest bar in the list.
    """
    if period <= 1:
        return None
    if len(bars) < period + 1:
        return None
    hist = bars[:-1]  # exclude current bar
    trs: List[float] = []
    prev_close: Optional[float] = None
    for b in hist[-(period + 1) :]:
        _o, h, l, c = _bar_ohlc(b)
        if h is None or l is None or c is None:
            return None
        if prev_close is None:
            tr = float(h - l)
        else:
            tr = max(float(h - l), abs(float(h - prev_close)), abs(float(l - prev_close)))
        trs.append(float(tr))
        prev_close = float(c)
    if len(trs) < period:
        return None
    # Use the last `period` TR values
    window = trs[-period:]
    return float(sum(window) / float(period))


def _compute_realized_vol(bars: List[Dict[str, Any]], period: int) -> Optional[float]:
    """
    Realized volatility proxy: std dev of log returns over last `period` closes.

    To avoid lookahead, uses closes excluding the latest bar.
    """
    if period <= 2:
        return None
    if len(bars) < period + 1:
        return None
    hist = bars[:-1]
    closes: List[float] = []
    for b in hist[-(period + 1) :]:
        _o, _h, _l, c = _bar_ohlc(b)
        if c is None or c <= 0:
            return None
        closes.append(float(c))
    if len(closes) < period + 1:
        return None
    rets: List[float] = []
    for i in range(1, len(closes)):
        rets.append(log(closes[i] / closes[i - 1]))
    if len(rets) < 2:
        return None
    mu = sum(rets) / float(len(rets))
    var = sum((r - mu) ** 2 for r in rets) / float(len(rets))
    return float(sqrt(max(0.0, var)))


def _position_for_symbol(account_snapshot: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    sym = str(symbol or "").upper().strip()
    positions = account_snapshot.get("positions") or []
    if not isinstance(positions, list):
        return None
    for p in positions:
        if not isinstance(p, dict):
            continue
        if str(p.get("symbol") or "").upper().strip() == sym:
            return p
    return None


class VolatilityBreakout(BaseStrategy):
    """
    Volatility / Breakout strategy with ATR-normalized channels.

    Breakout definition (symmetric):
    - upper = max(high) over lookback bars (excluding current)
    - lower = min(low) over lookback bars (excluding current)
    - long_breakout if close crosses above upper + buffer
    - short_breakout if close crosses below lower - buffer

    Exit definition (symmetric):
    - if in long and short_breakout => exit
    - if in short and long_breakout => exit (note: this repo's backtester doesn't open shorts)
    - time-based exit overrides (configured before close window)

    Volatility measures:
    - ATR: average true range (primary)
    - Realized vol: rolling std dev of log returns (secondary)
    - IV: optional from market_data ("implied_vol"|"iv"), pass-through only
    """

    TZ_NY = pytz.timezone("America/New_York")

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        self.lookback = int(self.config.get("lookback", 20))
        self.atr_period = int(self.config.get("atr_period", 14))
        self.realized_vol_period = int(self.config.get("realized_vol_period", 20))

        # Breakout buffer: either pct-of-level or ATR multiple (can use both).
        self.buffer_pct = float(self.config.get("breakout_buffer_pct", 0.0))
        self.buffer_atr_mult = float(self.config.get("breakout_buffer_atr_mult", 0.0))

        # Risk/exit knobs
        self.stop_atr_mult = float(self.config.get("stop_atr_mult", 2.0))
        self.max_hold_minutes = int(self.config.get("max_hold_minutes", 180))  # 3h default

        # Time-based exit is intentionally BEFORE close window by default.
        self.time_exit_ny = _parse_hhmm(str(self.config.get("time_exit_ny", "15:50")), default=dtime(15, 50))
        self.close_window_start_ny = _parse_hhmm(str(self.config.get("close_window_start_ny", "15:55")), default=dtime(15, 55))
        self.close_window_end_ny = _parse_hhmm(str(self.config.get("close_window_end_ny", "16:00")), default=dtime(16, 0))

        # Max notional per signal (USD). Enforced by clamping confidence -> allocation_pct.
        self.max_notional_per_signal_usd = float(self.config.get("max_notional_per_signal_usd", 1000.0))
        self.base_allocation_pct = float(self.config.get("base_allocation_pct", 0.10))

    def _apply_execution_safeguards(self, signal: TradingSignal) -> TradingSignal:
        if signal.signal_type not in {SignalType.BUY, SignalType.SELL, SignalType.CLOSE_ALL}:
            return signal

        allowed, deny_reason, env_snapshot = _execution_intent_allowed()
        if allowed:
            return signal

        logger.error(
            "EXECUTION SUPPRESSED by guardrails: intended_action=%s reason=%s env=%s",
            getattr(signal.signal_type, "value", str(signal.signal_type)),
            deny_reason,
            env_snapshot,
        )

        suppressed_metadata = dict(getattr(signal, "metadata", {}) or {})
        suppressed_metadata.update(
            {
                "execution_suppressed": True,
                "suppressed_reason": deny_reason,
                "suppressed_env": env_snapshot,
                "suppressed_intended_action": getattr(signal.signal_type, "value", str(signal.signal_type)),
                "suppressed_intended_confidence": getattr(signal, "confidence", None),
            }
        )
        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reasoning="Execution intent suppressed by safety guardrails.",
            metadata=suppressed_metadata,
        )

    def _maybe_sign(self, signal: TradingSignal) -> TradingSignal:
        """
        Best-effort Zero-Trust signing.

        Many unit tests and local runs instantiate strategies directly (without a StrategyLoader),
        so cryptographic identity is not configured. In that case, return the unsigned signal.
        """
        if getattr(self, "_identity_manager", None) is None or getattr(self, "_agent_id", None) is None:
            return signal
        try:
            return self.sign_signal(signal)
        except Exception:
            return signal

    def evaluate(self, market_data: Dict[str, Any], account_snapshot: Dict[str, Any], regime: Optional[str] = None) -> TradingSignal:
        _ = regime  # not used (volatility-only)
        symbol = str(market_data.get("symbol") or "").upper().strip() or "UNKNOWN"

        try:
            # Time context
            ts = _parse_iso_ts(market_data.get("timestamp")) or datetime.now(timezone.utc)
            ts_ny = _ny_time(ts, self.TZ_NY)

            # Market-close window: HOLD (no new risk, no churn)
            if ts_ny is not None:
                t = ts_ny.time()
                if self.close_window_start_ny <= t <= self.close_window_end_ny:
                    return self._maybe_sign(
                        TradingSignal(
                            signal_type=SignalType.HOLD,
                            symbol=symbol,
                            confidence=0.0,
                            reasoning="Market close window guardrail: HOLD (no entries/exits).",
                            metadata={
                                "guardrail": "market_close_window_hold",
                                "ts_ny": ts_ny.isoformat(),
                                "close_window_start_ny": self.close_window_start_ny.isoformat(),
                                "close_window_end_ny": self.close_window_end_ny.isoformat(),
                            },
                        )
                    )

            bars = _extract_bars(market_data)
            if len(bars) < (self.lookback + 2):
                # Fail-closed for insufficient data (enterprise-safe)
                return self._maybe_sign(
                    TradingSignal(
                        signal_type=SignalType.HOLD,
                        symbol=symbol,
                        confidence=0.0,
                        reasoning=f"Insufficient OHLC history for breakout/volatility computation (need >= {self.lookback+2}).",
                        metadata={"bars": len(bars), "lookback": self.lookback},
                    )
                )

            # Compute volatility measures
            iv = _as_float(market_data.get("implied_vol") or market_data.get("iv"))
            atr = _compute_atr(bars, self.atr_period)
            rvol = _compute_realized_vol(bars, self.realized_vol_period)
            vols = _VolMeasures(atr=atr, realized_vol=rvol, implied_vol=iv)

            # Extract current/prev close (for cross detection)
            _o0, _h0, _l0, close_prev = _bar_ohlc(bars[-2])
            _o1, _h1, _l1, close_now = _bar_ohlc(bars[-1])
            if close_prev is None or close_now is None:
                return self._maybe_sign(
                    TradingSignal(
                        signal_type=SignalType.HOLD,
                        symbol=symbol,
                        confidence=0.0,
                        reasoning="Missing close data in bars; HOLD.",
                    )
                )

            # Donchian channel (exclude current bar to avoid lookahead)
            hist = bars[:-1]
            highs = []
            lows = []
            for b in hist[-self.lookback :]:
                _o, h, l, _c = _bar_ohlc(b)
                if h is None or l is None:
                    return self._maybe_sign(
                        TradingSignal(
                            signal_type=SignalType.HOLD,
                            symbol=symbol,
                            confidence=0.0,
                            reasoning="Missing high/low data in bars; HOLD.",
                        )
                    )
                highs.append(float(h))
                lows.append(float(l))

            upper = max(highs)
            lower = min(lows)

            # Buffer: pct + ATR multiple
            buf = 0.0
            if self.buffer_pct > 0:
                buf += abs(float(upper)) * float(self.buffer_pct)
            if self.buffer_atr_mult > 0 and vols.atr is not None:
                buf += float(self.buffer_atr_mult) * float(vols.atr)

            upper_b = float(upper) + float(buf)
            lower_b = float(lower) - float(buf)

            long_cross = bool(float(close_prev) <= float(upper_b) and float(close_now) > float(upper_b))
            short_cross = bool(float(close_prev) >= float(lower_b) and float(close_now) < float(lower_b))

            # Position state
            pos = _position_for_symbol(account_snapshot, symbol)
            in_pos = pos is not None and float(pos.get("qty", 0) or 0) != 0.0
            entry_price = _as_float(pos.get("entry_price") if isinstance(pos, dict) else None)
            entry_time = _parse_iso_ts(pos.get("entry_time") if isinstance(pos, dict) else None)
            if entry_price is None:
                entry_price = _as_float(pos.get("avg_entry_price") if isinstance(pos, dict) else None)

            # Time-based exit (configurable)
            if in_pos and ts_ny is not None:
                # (a) absolute time exit
                if ts_ny.time() >= self.time_exit_ny:
                    sig = TradingSignal(
                        signal_type=SignalType.SELL,
                        symbol=symbol,
                        confidence=1.0,
                        reasoning=f"Time-based exit: {ts_ny.time().isoformat()} >= {self.time_exit_ny.isoformat()} NY.",
                        metadata={
                            "guardrail": "time_exit",
                            "ts_ny": ts_ny.isoformat(),
                            "time_exit_ny": self.time_exit_ny.isoformat(),
                        },
                    )
                    sig = self._apply_execution_safeguards(sig)
                    return self._maybe_sign(sig)

                # (b) max holding time exit (requires entry_time in snapshot)
                if entry_time is not None:
                    et_ny = _ny_time(entry_time, self.TZ_NY)
                    if et_ny is not None:
                        held_min = (ts_ny - et_ny).total_seconds() / 60.0
                        if held_min >= float(self.max_hold_minutes):
                            sig = TradingSignal(
                                signal_type=SignalType.SELL,
                                symbol=symbol,
                                confidence=1.0,
                                reasoning=f"Time-based exit: held {held_min:.1f}m >= max_hold_minutes={self.max_hold_minutes}.",
                                metadata={
                                    "guardrail": "max_hold_minutes",
                                    "held_minutes": float(held_min),
                                    "max_hold_minutes": int(self.max_hold_minutes),
                                    "entry_time_ny": et_ny.isoformat(),
                                    "ts_ny": ts_ny.isoformat(),
                                },
                            )
                            sig = self._apply_execution_safeguards(sig)
                            return self._maybe_sign(sig)

            # Stop loss (ATR-based, symmetric risk expression)
            stop_triggered = False
            stop_level = None
            if in_pos and entry_price is not None and vols.atr is not None and self.stop_atr_mult > 0:
                stop_level = float(entry_price) - float(self.stop_atr_mult) * float(vols.atr)
                stop_triggered = bool(float(close_now) <= float(stop_level))

            # Decide action (symmetric definition; executor may interpret SELL as enter-short when flat)
            action = SignalType.HOLD
            reason = "No breakout / no exit condition."

            if in_pos:
                if short_cross:
                    action = SignalType.SELL
                    reason = "Exit: opposite (short) breakout triggered (symmetry)."
                elif stop_triggered:
                    action = SignalType.SELL
                    reason = "Exit: ATR stop triggered."
            else:
                if long_cross:
                    action = SignalType.BUY
                    reason = "Entry: long breakout cross above channel."
                elif short_cross:
                    # Shorting support is executor-dependent; still emit a symmetric SELL signal.
                    action = SignalType.SELL
                    reason = "Entry: short breakout cross below channel (executor-dependent)."

            # Allocation / max-notional guardrail
            bp = None
            try:
                bp = float(str(account_snapshot.get("buying_power") or account_snapshot.get("cash") or "0").strip())
            except Exception:
                bp = None

            # Strength: distance beyond channel normalized by ATR (if available)
            strength = None
            if vols.atr is not None and float(vols.atr) > 0:
                if action == SignalType.BUY:
                    strength = (float(close_now) - float(upper_b)) / float(vols.atr)
                elif action == SignalType.SELL:
                    # for both exit or short entry, measure magnitude vs lower band
                    strength = (float(lower_b) - float(close_now)) / float(vols.atr)

            # Convert strength -> allocation_pct (bounded)
            allocation_pct = 0.0
            if action in {SignalType.BUY, SignalType.SELL}:
                base = max(0.0, float(self.base_allocation_pct))
                if strength is None:
                    allocation_pct = base
                else:
                    # clamp multiplier in [0.5, 2.0] for stability
                    mult = min(2.0, max(0.5, abs(float(strength))))
                    allocation_pct = min(1.0, base * mult)

            # Apply max-notional cap by clamping allocation_pct
            allocation_usd = None
            if bp is not None and bp > 0 and allocation_pct > 0:
                desired_usd = float(bp) * float(allocation_pct)
                cap_usd = max(0.0, float(self.max_notional_per_signal_usd))
                if cap_usd > 0:
                    allocation_usd = min(desired_usd, cap_usd)
                    allocation_pct = min(allocation_pct, float(allocation_usd) / float(bp))
                else:
                    allocation_usd = desired_usd

            sig = TradingSignal(
                signal_type=action,
                symbol=symbol,
                confidence=float(allocation_pct) if action != SignalType.HOLD else 0.0,
                reasoning=reason,
                metadata={
                    # Vol measures
                    "atr": vols.atr,
                    "realized_vol": vols.realized_vol,
                    "implied_vol": vols.implied_vol,
                    # Breakout channel
                    "lookback": int(self.lookback),
                    "upper": float(upper),
                    "lower": float(lower),
                    "buffer": float(buf),
                    "upper_b": float(upper_b),
                    "lower_b": float(lower_b),
                    "close_prev": float(close_prev),
                    "close_now": float(close_now),
                    "long_cross": bool(long_cross),
                    "short_cross": bool(short_cross),
                    # Risk/exit context
                    "in_position": bool(in_pos),
                    "entry_price": entry_price,
                    "stop_atr_mult": float(self.stop_atr_mult),
                    "stop_level": stop_level,
                    "stop_triggered": bool(stop_triggered),
                    # Allocation (enterprise guardrail)
                    "allocation_pct": float(allocation_pct),
                    "allocation_usd": allocation_usd,
                    "max_notional_per_signal_usd": float(self.max_notional_per_signal_usd),
                    "buying_power_usd": bp,
                    # Time context
                    "timestamp": ts.isoformat(),
                    "timestamp_ny": ts_ny.isoformat() if ts_ny is not None else None,
                },
            )

            sig = self._apply_execution_safeguards(sig)
            return self._maybe_sign(sig)

        except Exception as e:
            logger.exception("VolatilityBreakout.evaluate error: %s", e)
            sig = TradingSignal(
                signal_type=SignalType.HOLD,
                symbol=symbol,
                confidence=0.0,
                reasoning=f"Error evaluating VolatilityBreakout: {e}",
                metadata={"error": str(e)},
            )
            return self._maybe_sign(sig)
