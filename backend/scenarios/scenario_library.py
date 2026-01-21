from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from backend.strategy_runner.protocol import PROTOCOL_VERSION


def _parse_iso_to_utc(ts: str) -> datetime:
    """
    Parse ISO8601 timestamps, accepting trailing 'Z' for UTC.
    Returns an aware datetime in UTC.
    """
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt_utc.isoformat().replace("+00:00", "Z")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    out = _SLUG_RE.sub("_", s.strip().lower()).strip("_")
    return out or "scenario"


def _event_id(scenario_slug: str, idx: int) -> str:
    # protocol requires id: ^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$
    # Ensure it starts with alnum.
    return f"evt_{scenario_slug}_{idx:05d}"


@dataclass(frozen=True)
class Scenario:
    """
    A predefined market scenario that produces Strategy Runner protocol 'market_event' messages.
    """

    key: str
    name: str
    description: str


_SCENARIOS: Dict[str, Scenario] = {
    "quiet": Scenario(
        key="quiet",
        name="Quiet market",
        description="Low realized volatility, tight spreads, muted volume; mostly mean-reverting drift.",
    ),
    "high_volatility": Scenario(
        key="high_volatility",
        name="High volatility",
        description="Large intraday swings, wide spreads, elevated volume; frequent reversals.",
    ),
    "negative_gex": Scenario(
        key="negative_gex",
        name="Negative GEX day",
        description="Synthetic negative dealer gamma regime: choppy, trend-prone, wider realized moves.",
    ),
    "macro_event": Scenario(
        key="macro_event",
        name="Macro event day",
        description="Calm pre-event then a discontinuous jump and volatility expansion around the event time.",
    ),
    "power_hour_spike": Scenario(
        key="power_hour_spike",
        name="Power hour spike",
        description="Mostly range-bound session then an aggressive late-day rally with volume spike.",
    ),
}


def list_scenarios() -> List[Scenario]:
    return sorted(_SCENARIOS.values(), key=lambda s: s.key)


def get_scenario(key: str) -> Scenario:
    k = (key or "").strip()
    if not k:
        raise KeyError("scenario key is empty")
    if k not in _SCENARIOS:
        raise KeyError(f"unknown scenario: {k}")
    return _SCENARIOS[k]


def generate_market_events(
    *,
    scenario: str,
    symbol: str = "SPY",
    start_ts: str = "2025-01-01T14:30:00Z",
    steps: int = 390,
    interval_seconds: int = 60,
    seed: int = 7,
    start_price: float = 100.0,
    source: str = "sim",
    extra_payload: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Produce a deterministic list of protocol v1 'market_event' dicts.

    Notes:
    - Payload is intentionally generic and strategy-specific consumers can ignore fields.
    - `extra_payload` is merged into each event payload (caller wins on key collisions).
    """
    sc = get_scenario(scenario)
    if steps <= 0:
        return []
    interval_seconds = max(1, int(interval_seconds))

    rng = random.Random(int(seed))
    t0 = _parse_iso_to_utc(start_ts)
    scenario_slug = _slug(sc.key)

    # Helpers for synthetic microstructure.
    def make_spread(bp: float) -> float:
        # Spread as a fraction of price (basis points).
        return max(0.0001, float(bp) / 10_000.0)

    def clamp(x: float, lo: float, hi: float) -> float:
        return lo if x < lo else hi if x > hi else x

    def clamp_int(x: int, lo: int, hi: int) -> int:
        return lo if x < lo else hi if x > hi else x

    # Base parameters per scenario (kept simple/transparent).
    if sc.key == "quiet":
        # ~0.30% daily realized (very low), mild mean reversion.
        sigma = 0.0007
        drift = 0.0
        spread_bp = 0.6
        base_vol = 120_000
        gex = 1.2e9
        vol_regime = "low"
    elif sc.key == "high_volatility":
        # ~2.5% daily realized, occasional fat tails.
        sigma = 0.0045
        drift = 0.0
        spread_bp = 2.5
        base_vol = 650_000
        gex = 0.2e9
        vol_regime = "high"
    elif sc.key == "negative_gex":
        # Negative gamma: trend-prone + larger swings, higher sigma, slight downside skew.
        sigma = 0.0038
        drift = -0.00015
        spread_bp = 3.0
        base_vol = 700_000
        gex = -1.8e9
        vol_regime = "neg_gex"
    elif sc.key == "macro_event":
        # Pre-event calm, then jump and elevated vol.
        sigma = 0.0010
        drift = 0.0
        spread_bp = 1.2
        base_vol = 220_000
        gex = 0.6e9
        vol_regime = "macro_event"
    elif sc.key == "power_hour_spike":
        sigma = 0.0016
        drift = 0.0
        spread_bp = 1.0
        base_vol = 260_000
        gex = 0.9e9
        vol_regime = "power_hour"
    else:
        # Should never happen because get_scenario validates keys.
        sigma = 0.0015
        drift = 0.0
        spread_bp = 1.0
        base_vol = 200_000
        gex = 0.0
        vol_regime = "unknown"

    # Precompute event-specific regime modifiers.
    macro_event_idx = None
    if sc.key == "macro_event":
        # Default to a mid-session event (approx 2 hours after start for 1-min steps).
        macro_event_idx = clamp_int(int(steps * 0.35), 1, max(1, steps - 2))

    power_hour_start_idx = None
    if sc.key == "power_hour_spike":
        power_hour_start_idx = max(0, steps - int(math.ceil(3600 / interval_seconds)))

    price = float(start_price)
    last_r = 0.0
    events: List[Dict[str, Any]] = []

    for i in range(steps):
        ts_dt = t0 + timedelta(seconds=i * interval_seconds)

        # Scenario-specific volatility / drift modulation.
        local_sigma = sigma
        local_drift = drift
        local_spread_bp = spread_bp
        local_vol = base_vol
        payload_overrides: Dict[str, Any] = {}

        if sc.key == "high_volatility":
            # Occasional fat-tail moves.
            if rng.random() < 0.03:
                local_sigma *= 3.0
                payload_overrides["shock"] = {"kind": "fat_tail", "sigma_mult": 3.0}

        if sc.key == "negative_gex":
            # Negative gamma: moves amplify on trend (autocorrelation).
            if i > 0 and rng.random() < 0.55 and last_r != 0.0:
                local_drift += 0.00025 * (1.0 if last_r > 0.0 else -1.0)
            # Wider spreads when whipsawing.
            local_spread_bp *= 1.2

        if sc.key == "macro_event":
            if macro_event_idx is not None:
                if i < macro_event_idx:
                    local_sigma *= 0.6
                elif i == macro_event_idx:
                    # Discontinuous jump (either direction).
                    jump = rng.choice([-1.0, 1.0]) * rng.uniform(0.008, 0.018)
                    price *= 1.0 + jump
                    payload_overrides["macro_event"] = {
                        "kind": "scheduled_release",
                        "jump_return": jump,
                        "label": "CPI/FOMC-style shock",
                    }
                    local_sigma *= 4.0
                    local_spread_bp *= 3.5
                    local_vol *= 4
                else:
                    local_sigma *= 2.0
                    local_spread_bp *= 1.6
                    local_vol *= 2

        if sc.key == "power_hour_spike":
            if power_hour_start_idx is not None and i >= power_hour_start_idx:
                # Late-day upward squeeze.
                ramp = (i - power_hour_start_idx + 1) / max(1, steps - power_hour_start_idx)
                local_drift += 0.00035 + 0.00045 * ramp
                local_sigma *= 1.8
                local_spread_bp *= 1.4
                local_vol = int(base_vol * (2.0 + 2.5 * ramp))
                payload_overrides["session_phase"] = "power_hour"

        # Quiet market: mean-revert gently towards start_price to avoid drifting away.
        if sc.key == "quiet":
            mean_reversion = -0.02 * ((price - start_price) / max(1e-9, start_price))
            local_drift += mean_reversion
            local_sigma *= 0.9
            local_vol = int(base_vol * (0.7 + 0.4 * rng.random()))

        # Return process (simple, deterministic given seed).
        # Use a bounded normal-like via Box-Muller (random.gauss is fine too, but keep explicit).
        z = rng.gauss(0.0, 1.0)
        r = local_drift + local_sigma * z
        # Clamp single-interval returns to keep synthetic data sane.
        r = clamp(r, -0.08, 0.08)
        last_r = float(r)
        price *= 1.0 + r
        price = max(0.01, float(price))

        spread_frac = make_spread(local_spread_bp)
        bid = price * (1.0 - spread_frac / 2.0)
        ask = price * (1.0 + spread_frac / 2.0)

        payload: Dict[str, Any] = {
            "kind": "trade",
            "price": round(price, 4),
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "volume": int(max(1, local_vol * (0.6 + 0.8 * rng.random()))),
            "ret": round(r, 6),
            "regime": vol_regime,
            # Synthetic market structure fields for scenario-aware agents.
            "gex": float(gex),
        }
        payload.update(payload_overrides)
        if extra_payload:
            payload.update(dict(extra_payload))

        events.append(
            {
                "protocol": PROTOCOL_VERSION,
                "type": "market_event",
                "event_id": _event_id(scenario_slug, i + 1),
                "ts": _iso_utc(ts_dt),
                "symbol": str(symbol),
                "source": str(source),
                "payload": payload,
            }
        )

    return events


def scenario_key_aliases() -> Mapping[str, str]:
    """
    Human-friendly aliases -> canonical keys (kept stable for CLI UX).
    """
    return {
        "quiet_market": "quiet",
        "quiet": "quiet",
        "high_vol": "high_volatility",
        "high_volatility": "high_volatility",
        "neg_gex": "negative_gex",
        "negative_gex": "negative_gex",
        "macro": "macro_event",
        "macro_event": "macro_event",
        "power_hour": "power_hour_spike",
        "power_hour_spike": "power_hour_spike",
    }


def normalize_scenario_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        raise KeyError("scenario key is empty")
    aliases = scenario_key_aliases()
    return aliases.get(k, k)


def generate_market_events_for_key(
    *,
    scenario_key: str,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper that accepts aliases (e.g., 'quiet_market', 'neg_gex').
    """
    return generate_market_events(scenario=normalize_scenario_key(scenario_key), **kwargs)


def to_ndjson_lines(events: Iterable[Dict[str, Any]]) -> str:
    """
    Render one JSON object per line (NDJSON) with a trailing newline.
    """
    import json

    return "\n".join(json.dumps(e, separators=(",", ":"), ensure_ascii=False) for e in events) + "\n"

