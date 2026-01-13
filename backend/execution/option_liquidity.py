from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


_OCC_LIKE_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def is_option_contract_symbol(symbol: str | None) -> bool:
    """
    Best-effort OCC-like contract symbol detection.

    Examples (common in Alpaca / OCC-style):
      - SPY240119C00475000
      - AAPL260117P00150000
    """
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    return bool(_OCC_LIKE_RE.match(s))


@dataclass(frozen=True, slots=True)
class OptionLiquidityThresholds:
    min_open_interest: int
    min_volume: int
    max_spread_pct_of_mid: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_open_interest": int(self.min_open_interest),
            "min_volume": int(self.min_volume),
            "max_spread_pct_of_mid": float(self.max_spread_pct_of_mid),
        }


def load_thresholds_from_env() -> OptionLiquidityThresholds:
    """
    Load option liquidity thresholds from environment variables.

    Defaults are conservative and intended for paper trading safety.
    """
    min_oi = int(os.getenv("OPTIONS_MIN_OPEN_INTEREST") or "100")
    min_vol = int(os.getenv("OPTIONS_MIN_VOLUME") or "10")
    max_spread_pct = float(os.getenv("OPTIONS_MAX_SPREAD_PCT") or "0.25")

    # Fail-safe normalization
    min_oi = max(0, min_oi)
    min_vol = max(0, min_vol)
    max_spread_pct = max(0.0, max_spread_pct)

    return OptionLiquidityThresholds(
        min_open_interest=min_oi,
        min_volume=min_vol,
        max_spread_pct_of_mid=max_spread_pct,
    )


def _as_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _as_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        # Many upstreams serialize numbers as strings.
        return int(float(v))
    except Exception:
        return None


def extract_liquidity_metrics(*, source: dict[str, Any]) -> dict[str, Any]:
    """
    Extract open interest, volume, and bid/ask from a best-effort source dict.

    Supports:
    - flattened metrics (bid/ask/open_interest/volume)
    - Alpaca options snapshot payloads (latestQuote/dailyBar/openInterest, etc.)
    """
    src = dict(source or {})

    # Direct fields (metadata / normalized quote dicts)
    bid = _as_float(src.get("bid") or src.get("bid_price") or src.get("bp"))
    ask = _as_float(src.get("ask") or src.get("ask_price") or src.get("ap"))
    oi = _as_int(src.get("open_interest") or src.get("openInterest") or src.get("oi"))
    vol = _as_int(src.get("volume") or src.get("vol"))

    # Nested Alpaca snapshot fields
    latest_quote = src.get("latestQuote") or src.get("latest_quote") or src.get("quote") or {}
    if isinstance(latest_quote, dict):
        bid = bid if bid is not None else _as_float(latest_quote.get("bp") or latest_quote.get("bid_price") or latest_quote.get("bidPrice"))
        ask = ask if ask is not None else _as_float(latest_quote.get("ap") or latest_quote.get("ask_price") or latest_quote.get("askPrice"))

    daily_bar = src.get("dailyBar") or src.get("daily_bar") or {}
    if isinstance(daily_bar, dict):
        vol = vol if vol is not None else _as_int(daily_bar.get("v") or daily_bar.get("volume"))

    # Some snapshots use camelCase
    oi = oi if oi is not None else _as_int(src.get("openInterest"))
    vol = vol if vol is not None else _as_int(src.get("volume"))

    # Derive mid/spread
    mid = None
    spread = None
    spread_pct = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        spread = ask - bid
        if mid > 0:
            spread_pct = spread / mid

    return {
        "open_interest": oi,
        "volume": vol,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
    }


def evaluate_option_liquidity(
    *,
    symbol: str,
    thresholds: OptionLiquidityThresholds,
    metrics: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    """
    Returns: (allowed, reason_codes, details)
    """
    reasons: list[str] = []
    m = dict(metrics or {})

    oi = _as_int(m.get("open_interest"))
    vol = _as_int(m.get("volume"))
    bid = _as_float(m.get("bid"))
    ask = _as_float(m.get("ask"))
    mid = _as_float(m.get("mid"))
    spread_pct = _as_float(m.get("spread_pct"))

    # Basic quote sanity (misleading contracts / broken quotes)
    if bid is None or ask is None:
        reasons.append("missing_bid_or_ask")
    else:
        if bid <= 0 or ask <= 0:
            reasons.append("non_positive_bid_or_ask")
        if ask < bid:
            reasons.append("crossed_market_ask_lt_bid")
    if mid is None or mid <= 0:
        reasons.append("invalid_mid_price")
    if spread_pct is None or spread_pct < 0:
        reasons.append("invalid_spread_pct")

    # Liquidity thresholds
    if oi is None:
        reasons.append("missing_open_interest")
    elif oi < int(thresholds.min_open_interest):
        reasons.append("open_interest_below_min")

    if vol is None:
        reasons.append("missing_volume")
    elif vol < int(thresholds.min_volume):
        reasons.append("volume_below_min")

    if spread_pct is not None and spread_pct >= 0:
        if spread_pct > float(thresholds.max_spread_pct_of_mid):
            reasons.append("spread_pct_above_max")

    allowed = len(reasons) == 0
    details = {
        "symbol": str(symbol),
        "metrics": {
            "open_interest": oi,
            "volume": vol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pct": spread_pct,
        },
        "thresholds": thresholds.to_dict(),
    }
    return allowed, reasons, details

