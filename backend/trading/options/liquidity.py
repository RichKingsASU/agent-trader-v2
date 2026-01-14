from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            try:
                f = float(s)
                return int(f) if f.is_integer() else None
            except Exception:
                return None
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _dig(d: Any, *keys: str) -> Any:
    """
    Best-effort nested dict getter.
    Returns the first non-None match following the given key path(s).
    """
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        if k not in cur:
            return None
        cur = cur.get(k)
    return cur


@dataclass(frozen=True)
class OptionLiquidityThresholds:
    """
    Liquidity gates for option contracts.

    - min_open_interest: minimum open interest (contracts)
    - min_volume: minimum volume (contracts) (typically daily)
    - max_spread_pct: maximum bid/ask spread as % of mid (0.20 = 20%)
    """

    min_open_interest: int = 50
    min_volume: int = 10
    max_spread_pct: float = 0.20

    @staticmethod
    def from_env() -> "OptionLiquidityThresholds":
        def _int(name: str, default: int) -> int:
            v = os.getenv(name)
            parsed = _as_int(v)
            if parsed is None:
                return int(default)
            return max(0, int(parsed))

        def _pct(name: str, default: float) -> float:
            v = os.getenv(name)
            parsed = _as_float(v)
            if parsed is None:
                return float(default)
            x = float(parsed)
            # Support "percent" inputs like 20 => 20%.
            if x > 1.0:
                x = x / 100.0
            return max(0.0, float(x))

        return OptionLiquidityThresholds(
            min_open_interest=_int("OPTION_LIQ_MIN_OPEN_INTEREST", 50),
            min_volume=_int("OPTION_LIQ_MIN_VOLUME", 10),
            max_spread_pct=_pct("OPTION_LIQ_MAX_SPREAD_PCT", 0.20),
        )


@dataclass(frozen=True)
class OptionLiquidityObservation:
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    spread: Optional[float]
    spread_pct: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]


@dataclass(frozen=True)
class OptionLiquidityDecision:
    allowed: bool
    reason: str
    observation: OptionLiquidityObservation


def extract_liquidity_fields(snapshot_payload: dict[str, Any]) -> OptionLiquidityObservation:
    """
    Extract bid/ask/volume/open_interest from an Alpaca option snapshot payload.

    Supports multiple shapes:
    - flat keys: bid/ask/volume/open_interest
    - nested (common in vendor snapshots): latestQuote / quote, latestTrade, greeks, etc.
    """
    p = snapshot_payload or {}

    # Bid/ask can appear in several places; check common variants.
    bid = (
        _as_float(p.get("bid"))
        or _as_float(p.get("bid_price"))
        or _as_float(_dig(p, "quote", "bid"))
        or _as_float(_dig(p, "quote", "bp"))
        or _as_float(_dig(p, "latestQuote", "bp"))
        or _as_float(_dig(p, "latest_quote", "bp"))
        or _as_float(_dig(p, "latestQuote", "bid_price"))
        or _as_float(_dig(p, "latest_quote", "bid_price"))
    )
    ask = (
        _as_float(p.get("ask"))
        or _as_float(p.get("ask_price"))
        or _as_float(_dig(p, "quote", "ask"))
        or _as_float(_dig(p, "quote", "ap"))
        or _as_float(_dig(p, "latestQuote", "ap"))
        or _as_float(_dig(p, "latest_quote", "ap"))
        or _as_float(_dig(p, "latestQuote", "ask_price"))
        or _as_float(_dig(p, "latest_quote", "ask_price"))
    )

    # Volume / OI typically included at top-level in our normalized Firestore payload, but
    # allow nested variants too.
    volume = _as_int(p.get("volume")) or _as_int(_dig(p, "daily", "volume")) or _as_int(_dig(p, "stats", "volume"))
    open_interest = (
        _as_int(p.get("open_interest"))
        or _as_int(p.get("openInterest"))
        or _as_int(_dig(p, "stats", "open_interest"))
        or _as_int(_dig(p, "stats", "openInterest"))
    )

    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = (spread / mid) if mid > 0 else None
    else:
        mid = None
        spread = None
        spread_pct = None

    return OptionLiquidityObservation(
        bid=bid,
        ask=ask,
        mid=mid,
        spread=spread,
        spread_pct=spread_pct,
        volume=volume,
        open_interest=open_interest,
    )


def evaluate_option_liquidity(
    *,
    snapshot_payload: dict[str, Any],
    thresholds: OptionLiquidityThresholds,
) -> OptionLiquidityDecision:
    """
    Returns an allow/deny decision for an option contract based on snapshot fields.

    Fail-closed: missing critical fields causes rejection.
    """
    obs = extract_liquidity_fields(snapshot_payload)

    if obs.bid is None or obs.ask is None or obs.bid <= 0 or obs.ask <= 0:
        return OptionLiquidityDecision(False, "missing_bid_ask", obs)
    if obs.ask < obs.bid:
        return OptionLiquidityDecision(False, "crossed_market", obs)
    if obs.mid is None or obs.mid <= 0 or obs.spread_pct is None:
        return OptionLiquidityDecision(False, "missing_mid_or_spread", obs)

    if obs.open_interest is None:
        return OptionLiquidityDecision(False, "missing_open_interest", obs)
    if obs.open_interest < int(thresholds.min_open_interest):
        return OptionLiquidityDecision(False, "open_interest_below_min", obs)

    if obs.volume is None:
        return OptionLiquidityDecision(False, "missing_volume", obs)
    if obs.volume < int(thresholds.min_volume):
        return OptionLiquidityDecision(False, "volume_below_min", obs)

    if float(obs.spread_pct) > float(thresholds.max_spread_pct):
        return OptionLiquidityDecision(False, "spread_pct_above_max", obs)

    return OptionLiquidityDecision(True, "ok", obs)

