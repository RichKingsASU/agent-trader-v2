from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

from backend.streams.alpaca_env import load_alpaca_env

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OptionLiquidityThresholds:
    """
    Liquidity thresholds for option contracts.

    All thresholds are fail-closed by default: if we cannot obtain metrics,
    the contract is treated as non-tradable to avoid misleading paper fills.
    """

    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct_of_mid: float = 0.15  # 15% of mid
    enabled: bool = True
    fail_open: bool = False

    @staticmethod
    def from_env() -> "OptionLiquidityThresholds":
        def _bool(name: str, default: bool) -> bool:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

        def _int(name: str, default: int) -> int:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return int(default)
            return int(float(str(v).strip()))

        def _float(name: str, default: float) -> float:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return float(default)
            return float(str(v).strip())

        enabled = _bool("OPTION_LIQ_ENABLED", True)
        fail_open = _bool("OPTION_LIQ_FAIL_OPEN", False)
        return OptionLiquidityThresholds(
            min_open_interest=max(0, _int("OPTION_LIQ_MIN_OPEN_INTEREST", 100)),
            min_volume=max(0, _int("OPTION_LIQ_MIN_VOLUME", 10)),
            max_spread_pct_of_mid=max(0.0, _float("OPTION_LIQ_MAX_SPREAD_PCT", 0.15)),
            enabled=enabled,
            fail_open=fail_open,
        )


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None
    return None


def _as_float(value: Any) -> float | None:
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


def _get_nested(d: dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _first_present(*vals: Any) -> Any:
    """
    Return first value that is not None / not empty-string.

    Important: unlike `a or b`, this preserves valid falsy values like 0.
    """
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return v
    return None


def extract_option_liquidity_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort parse of Alpaca option snapshot payload into stable metrics.

    We intentionally accept multiple key spellings because Alpaca payloads vary
    across endpoints / versions.
    """
    # Quote (bid/ask)
    q = (
        _get_nested(snapshot, "latestQuote")
        or _get_nested(snapshot, "latest_quote")
        or _get_nested(snapshot, "quote")
        or {}
    )
    bid = _as_float(_first_present(q.get("bp"), q.get("bid_price"), q.get("bid"), q.get("b")))
    ask = _as_float(_first_present(q.get("ap"), q.get("ask_price"), q.get("ask"), q.get("a")))
    bid = float(bid or 0.0)
    ask = float(ask or 0.0)
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(bid or ask or 0.0)
    spread = float(max(0.0, ask - bid)) if bid > 0 and ask > 0 else 0.0
    spread_pct = float(spread / mid) if mid > 0 and spread > 0 else 0.0

    # Volume (prefer dailyBar)
    daily_bar = _get_nested(snapshot, "dailyBar") or _get_nested(snapshot, "daily_bar") or {}
    volume = _as_int(_first_present(daily_bar.get("v"), daily_bar.get("volume"), snapshot.get("volume")))

    # Open interest
    open_interest = _as_int(
        _first_present(
            snapshot.get("open_interest"),
            snapshot.get("openInterest"),
            _get_nested(snapshot, "openInterest"),
            _get_nested(snapshot, "open_interest"),
        )
    )

    # Timestamp (optional, informational)
    ts = (
        q.get("t")
        or q.get("timestamp")
        or snapshot.get("timestamp")
        or snapshot.get("snapshot_time")
        or None
    )

    return {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
        "volume": volume,
        "open_interest": open_interest,
        "timestamp": ts,
    }


def evaluate_option_liquidity(
    *,
    option_symbol: str,
    metrics: dict[str, Any],
    thresholds: OptionLiquidityThresholds,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Returns (allowed, reason_code, details).
    """
    t = thresholds
    details = {
        "symbol": option_symbol,
        "thresholds": {
            "min_open_interest": t.min_open_interest,
            "min_volume": t.min_volume,
            "max_spread_pct_of_mid": t.max_spread_pct_of_mid,
            "enabled": t.enabled,
            "fail_open": t.fail_open,
        },
        "metrics": {
            "open_interest": metrics.get("open_interest"),
            "volume": metrics.get("volume"),
            "bid": metrics.get("bid"),
            "ask": metrics.get("ask"),
            "mid": metrics.get("mid"),
            "spread": metrics.get("spread"),
            "spread_pct": metrics.get("spread_pct"),
            "timestamp": metrics.get("timestamp"),
        },
    }

    if not t.enabled:
        return True, "option_liquidity_disabled", details

    oi = metrics.get("open_interest")
    vol = metrics.get("volume")
    spread_pct = float(metrics.get("spread_pct") or 0.0)

    missing = []
    if oi is None:
        missing.append("open_interest")
    if vol is None:
        missing.append("volume")

    # Bid/ask/mid missing => spread pct == 0; treat as missing quote.
    bid = float(metrics.get("bid") or 0.0)
    ask = float(metrics.get("ask") or 0.0)
    mid = float(metrics.get("mid") or 0.0)
    if bid <= 0 or ask <= 0 or mid <= 0:
        missing.append("quote")

    if missing:
        if t.fail_open:
            return True, "option_liquidity_data_missing_fail_open", {**details, "missing": missing}
        return False, "option_liquidity_data_missing", {**details, "missing": missing}

    if int(oi) < int(t.min_open_interest):
        return False, "option_open_interest_below_min", details
    if int(vol) < int(t.min_volume):
        return False, "option_volume_below_min", details
    if spread_pct > float(t.max_spread_pct_of_mid):
        return False, "option_spread_too_wide", details

    return True, "option_liquidity_ok", details


def fetch_alpaca_option_snapshot(*, option_symbol: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """
    Fetch a single option snapshot via Alpaca data API.

    Uses:
      GET {DATA_BASE}/v1beta1/options/snapshots?symbols={SYMBOL}
    """
    alpaca = load_alpaca_env(require_keys=True)
    base = str(alpaca.data_base_v2).rstrip("/")
    url = f"{base}/v1beta1/options/snapshots"
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}

    sym = str(option_symbol).strip().upper()
    r = requests.get(url, headers=headers, params={"symbols": sym}, timeout=timeout_s)
    r.raise_for_status()
    payload = r.json() or {}

    snaps = payload.get("snapshots") if isinstance(payload, dict) else None
    if not isinstance(snaps, dict):
        # Some endpoints may return the dict directly; treat payload as snapshots.
        snaps = payload if isinstance(payload, dict) else {}

    snap = snaps.get(sym)
    if not isinstance(snap, dict):
        # Try alternate key if API returns a prefixed form.
        alt = f"O:{sym}"
        snap = snaps.get(alt)
    if not isinstance(snap, dict):
        raise RuntimeError(f"option_snapshot_missing symbol={sym}")
    return snap

