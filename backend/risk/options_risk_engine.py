"""
Shadow-only options risk engine.

This module evaluates an `OptionOrderIntent` against configurable limits using
only *local inputs*:
- the proposed intent (no broker assumptions; no fill checks)
- current *shadow* exposures/positions (passed in by caller)
- an optional market regime hint (passed in by caller)

Safety and determinism:
- No randomness.
- No external I/O.
- No broker queries.
- Does NOT modify or persist any state.

The engine is intentionally conservative: it evaluates the *worst-case* impact
of the intent as if it were fully filled immediately at the stated contract
count. (This is not a broker assumption; it's a safety assumption.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Union

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from backend.risk.reason_codes import RiskReasonCode
from backend.time import nyse_time


class OptionSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class OptionOrderIntent(BaseModel):
    """
    Proposed options order for risk evaluation (shadow-only).

    Notes on greeks:
    - `delta` and `gamma` are expected in *per-share* greek units as commonly
      quoted by market data providers (e.g., delta ~ 0.50 for ATM call).
    - Exposure is computed as: greek * contract_multiplier * contracts * side_sign
      where side_sign is +1 for BUY and -1 for SELL.

    Notes on quantity:
    - `contracts` MUST be positive. Direction is conveyed by `side`.

    Notes on determinism:
    - This object contains no timestamps; the evaluator accepts an explicit `now`
      for reproducibility.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    underlying_symbol: str = Field(..., min_length=1)
    expiration: date
    right: OptionRight
    strike: float = Field(..., gt=0)

    # Optional identifiers (OCC/OPRA/etc.) for logging only; not required.
    contract_symbol: Optional[str] = None

    side: OptionSide
    # Explicitly declare whether this intent is opening or closing exposure.
    # This is critical for time-of-day logic (risk-increasing vs risk-reducing),
    # and avoids any broker/position inference.
    #
    # - "OPEN": increases exposure/open interest (e.g., buy-to-open, sell-to-open)
    # - "CLOSE": reduces existing exposure (e.g., sell-to-close, buy-to-close)
    # - "UNKNOWN": caller did not specify; treated conservatively in cutoff logic
    position_effect: str = Field(default="UNKNOWN", pattern="^(OPEN|CLOSE|UNKNOWN)$")
    contracts: int = Field(..., gt=0)
    contract_multiplier: int = Field(default=100, gt=0)

    # Per-share greeks; optional but required for delta/gamma checks.
    delta: Optional[float] = None
    gamma: Optional[float] = None


class ShadowExposureSnapshot(BaseModel):
    """
    Caller-provided snapshot of current shadow exposures.

    This is intentionally small and aggregation-based. If a caller has detailed
    position data, it should pre-aggregate to these fields deterministically.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Current total open option contracts (absolute count across legs).
    open_contracts: int = Field(default=0, ge=0)

    # Contracts traded today (absolute count), used for max-per-day throttles.
    contracts_traded_today: int = Field(default=0, ge=0)

    # Net greeks for the book (signed).
    net_delta: float = 0.0
    net_gamma: float = 0.0


@dataclass(frozen=True, slots=True)
class OptionsRiskLimits:
    """
    Risk limits (defaults are conservative placeholders).

    These are intentionally simple scalar limits. More complex cross-greek or
    scenario-based constraints can be layered on later.
    """

    max_contracts_per_trade: int = 10
    max_contracts_per_day: int = 25

    # Absolute limits on post-trade net exposure (signed then abs()).
    max_abs_net_delta: float = 5_000.0  # delta shares equivalent
    max_abs_net_gamma: float = 2_000.0  # gamma shares/underlier-unit equivalent
    max_abs_net_gamma_0dte: float = 500.0  # tighter gamma cap for 0DTE

    # Time-of-day cutoff: no new risk after 15:30 ET (risk-reducing trades allowed).
    cutoff_time_et: time = time(15, 30)


def _side_sign(side: OptionSide) -> int:
    return 1 if side == OptionSide.BUY else -1


def _coerce_snapshot(shadow_positions: Union[ShadowExposureSnapshot, Mapping[str, Any], None]) -> ShadowExposureSnapshot:
    if shadow_positions is None:
        return ShadowExposureSnapshot()
    if isinstance(shadow_positions, ShadowExposureSnapshot):
        return shadow_positions
    if isinstance(shadow_positions, Mapping):
        # Best-effort coercion; strict keys enforced by the model (extra="forbid").
        return ShadowExposureSnapshot.model_validate(dict(shadow_positions))
    raise TypeError("shadow_positions must be a ShadowExposureSnapshot, mapping, or None")


def _market_regime_tightening_factor(market_regime: Optional[Mapping[str, Any]]) -> float:
    """
    Optional regime hint -> multiplicative tightening factor.

    Deterministic and intentionally simple:
    - If market_regime indicates 'risk_off' or 'high_vol', tighten by 20%.
    - Otherwise 1.0.
    """

    if not market_regime:
        return 1.0
    try:
        risk_off = bool(market_regime.get("risk_off", False))
        high_vol = str(market_regime.get("volatility", "")).strip().lower() in {"high", "elevated"}
        if risk_off or high_vol:
            return 0.8
    except Exception:
        # If the hint is malformed, ignore it deterministically.
        return 1.0
    return 1.0


def evaluate_option_order_intent(
    intent: OptionOrderIntent,
    shadow_positions: Union[ShadowExposureSnapshot, Mapping[str, Any], None],
    market_regime: Optional[Mapping[str, Any]] = None,
    *,
    limits: OptionsRiskLimits = OptionsRiskLimits(),
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Evaluate an `OptionOrderIntent` against shadow-only risk constraints.

    Returns:
        {
          "allowed": bool,
          "reason_code": str,
          "human_reason": str,
          "metrics": { ... }
        }

    Rules implemented:
    - Max contracts per trade.
    - Max contracts per day.
    - Max absolute net delta (post-trade).
    - Max absolute net gamma exposure (post-trade), with tighter cap for 0DTE.
    - Time-of-day guard: after 15:30 ET, only risk-reducing intents are allowed.

    Important:
    - This function assumes the intent is fully filled for risk accounting.
    - No broker queries, no fills, no state changes.
    - Pass an explicit `now` (tz-aware UTC recommended) for deterministic tests.
    """

    snap = _coerce_snapshot(shadow_positions)
    now_utc = nyse_time.to_utc(now) if now is not None else nyse_time.utc_now()
    now_et = nyse_time.to_nyse(now_utc)

    # Compute DTE in ET calendar terms (0DTE iff expiration == today's ET date).
    today_et = now_et.date()
    dte = (intent.expiration - today_et).days
    is_0dte = dte == 0

    # Contracts checks are always available.
    trade_contracts = int(intent.contracts)
    day_contracts_after = int(snap.contracts_traded_today) + trade_contracts

    # Greeks checks require greeks.
    sign = _side_sign(intent.side)
    delta_contrib: Optional[float]
    gamma_contrib: Optional[float]
    if intent.delta is None:
        delta_contrib = None
    else:
        delta_contrib = float(intent.delta) * float(intent.contract_multiplier) * float(trade_contracts) * float(sign)
    if intent.gamma is None:
        gamma_contrib = None
    else:
        gamma_contrib = float(intent.gamma) * float(intent.contract_multiplier) * float(trade_contracts) * float(sign)

    net_delta_before = float(snap.net_delta)
    net_gamma_before = float(snap.net_gamma)
    net_delta_after = net_delta_before + (delta_contrib or 0.0)
    net_gamma_after = net_gamma_before + (gamma_contrib or 0.0)

    open_contracts_before = int(snap.open_contracts)
    # For reporting only: attempt to estimate open contracts after, without
    # inferring broker fills or position matching. If the caller declares CLOSE,
    # treat it as reducing open contracts; otherwise treat as adding exposure.
    if intent.position_effect == "CLOSE":
        open_contracts_after = max(open_contracts_before - trade_contracts, 0)
    else:
        open_contracts_after = open_contracts_before + trade_contracts

    # Regime tightening (optional) applied to delta/gamma limits only.
    tighten = _market_regime_tightening_factor(market_regime)
    max_abs_net_delta = limits.max_abs_net_delta * tighten
    max_abs_net_gamma = (limits.max_abs_net_gamma_0dte if is_0dte else limits.max_abs_net_gamma) * tighten

    cutoff_passed = now_et.timetz().replace(tzinfo=None) >= limits.cutoff_time_et

    metrics: Dict[str, Any] = {
        "now_utc": now_utc.isoformat(),
        "now_et": now_et.isoformat(),
        "cutoff_time_et": limits.cutoff_time_et.isoformat(timespec="minutes"),
        "cutoff_passed": cutoff_passed,
        "expiration": intent.expiration.isoformat(),
        "dte_et": dte,
        "is_0dte": is_0dte,
        "trade_contracts": trade_contracts,
        "contracts_traded_today_before": int(snap.contracts_traded_today),
        "contracts_traded_today_after": day_contracts_after,
        "open_contracts_before": open_contracts_before,
        "open_contracts_after": open_contracts_after,
        "net_delta_before": net_delta_before,
        "net_delta_after": net_delta_after,
        "net_gamma_before": net_gamma_before,
        "net_gamma_after": net_gamma_after,
        "delta_contrib": delta_contrib,
        "gamma_contrib": gamma_contrib,
        "limits": {
            "max_contracts_per_trade": limits.max_contracts_per_trade,
            "max_contracts_per_day": limits.max_contracts_per_day,
            "max_abs_net_delta": max_abs_net_delta,
            "max_abs_net_gamma": max_abs_net_gamma,
            "tightening_factor": tighten,
        },
        "missing_greeks": {
            "delta": intent.delta is None,
            "gamma": intent.gamma is None,
        },
    }

    # 1) Max contracts per trade
    if trade_contracts > limits.max_contracts_per_trade:
        return {
            "allowed": False,
            "reason_code": RiskReasonCode.MAX_CONTRACTS_PER_TRADE,
            "human_reason": f"Trade size {trade_contracts} exceeds max contracts per trade {limits.max_contracts_per_trade}.",
            "metrics": metrics,
        }

    # 2) Max contracts per day
    if day_contracts_after > limits.max_contracts_per_day:
        return {
            "allowed": False,
            "reason_code": RiskReasonCode.MAX_CONTRACTS_PER_DAY,
            "human_reason": (
                f"Contracts today {day_contracts_after} would exceed max contracts per day {limits.max_contracts_per_day}."
            ),
            "metrics": metrics,
        }

    # 3) Time-of-day guard (after cutoff allow only risk-reducing)
    if cutoff_passed:
        # After 15:30 ET, we disallow *new* risk. We interpret "new risk" in greek
        # terms (delta/gamma) when available. If greeks are missing, only explicit
        # CLOSE intents are allowed.
        if (intent.delta is None or intent.gamma is None) and intent.position_effect != "CLOSE":
            return {
                "allowed": False,
                "reason_code": RiskReasonCode.TIME_OF_DAY_CUTOFF,
                "human_reason": "After 15:30 ET, new risk is not allowed (requires greeks or explicit CLOSE).",
                "metrics": metrics,
            }

        if intent.delta is not None and abs(net_delta_after) > abs(net_delta_before):
            return {
                "allowed": False,
                "reason_code": RiskReasonCode.TIME_OF_DAY_CUTOFF,
                "human_reason": "After 15:30 ET only delta-reducing trades are allowed.",
                "metrics": metrics,
            }
        if intent.gamma is not None and abs(net_gamma_after) > abs(net_gamma_before):
            return {
                "allowed": False,
                "reason_code": RiskReasonCode.TIME_OF_DAY_CUTOFF,
                "human_reason": "After 15:30 ET only gamma-reducing trades are allowed.",
                "metrics": metrics,
            }

    # 4) Max net delta (requires delta)
    if intent.delta is not None and abs(net_delta_after) > max_abs_net_delta:
        return {
            "allowed": False,
            "reason_code": RiskReasonCode.MAX_NET_DELTA,
            "human_reason": f"Post-trade net delta {net_delta_after:.2f} exceeds limit ±{max_abs_net_delta:.2f}.",
            "metrics": metrics,
        }

    # 5) Max gamma exposure (requires gamma); 0DTE tighter
    if intent.gamma is not None and abs(net_gamma_after) > max_abs_net_gamma:
        cap_label = "0DTE gamma cap" if is_0dte else "gamma cap"
        return {
            "allowed": False,
            "reason_code": RiskReasonCode.MAX_GAMMA_EXPOSURE,
            "human_reason": f"Post-trade net gamma {net_gamma_after:.2f} exceeds {cap_label} ±{max_abs_net_gamma:.2f}.",
            "metrics": metrics,
        }

    # If greeks are missing, we still allow based on contract throttles and time guard.
    # Callers that want stricter behavior can deny upstream when greeks are absent.
    return {
        "allowed": True,
        "reason_code": RiskReasonCode.OK,
        "human_reason": "Allowed by shadow options risk checks.",
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Example allow/deny cases (illustrative; not executed)
# ---------------------------------------------------------------------------
#
# Example 1 (ALLOW): within all limits
# intent = OptionOrderIntent(
#   underlying_symbol="SPY",
#   expiration=date(2026, 1, 21),
#   right="CALL",
#   strike=480.0,
#   side="BUY",
#   contracts=1,
#   delta=0.50,
#   gamma=0.08,
# )
# shadow = {"open_contracts": 0, "contracts_traded_today": 0, "net_delta": 0.0, "net_gamma": 0.0}
# evaluate_option_order_intent(intent, shadow, now=datetime(2026,1,21,14,0,tzinfo=ZoneInfo("UTC")))
#
# Example 2 (DENY): exceeds per-trade contracts
# intent.contracts = 50  # > max_contracts_per_trade
#
# Example 3 (DENY): 0DTE gamma tighter cap
# intent.expiration = today_et; intent.gamma high so abs(net_gamma_after) > max_abs_net_gamma_0dte
#
# Example 4 (DENY): after 15:30 ET, intent increases open contracts
# now_et = 15:45; position_effect="OPEN" and increases abs(net_delta)/abs(net_gamma) -> TIME_OF_DAY_CUTOFF
#
# Example 5 (ALLOW): after 15:30 ET, explicit CLOSE that reduces exposure
# now_et = 15:45; position_effect="CLOSE" and reduces abs(net_delta), abs(net_gamma)


__all__ = [
    "OptionOrderIntent",
    "ShadowExposureSnapshot",
    "OptionsRiskLimits",
    "evaluate_option_order_intent",
]

