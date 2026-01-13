from __future__ import annotations

"""
Options P&L attribution helpers.

Scope:
- This module does NOT try to fully re-price options (no BS engine here).
- It provides a deterministic decomposition of observed option price changes into
  greek-style components, given two snapshots.

Intended use:
- explainability / audit reports
- operator-facing breakdowns (delta/gamma/vega/theta + residual)
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GreeksSnapshot:
    ts: datetime
    option_price: float  # quoted option price (typically $/share premium)
    underlying_price: float
    iv: float  # implied volatility as a decimal (e.g. 0.20 for 20%)

    delta: float
    gamma: float
    vega: float
    theta: float  # theta per DAY (common convention)


@dataclass(frozen=True, slots=True)
class OptionMtmAttribution:
    qty: float
    multiplier: float

    total_mtm_pnl: float
    delta_pnl: float
    gamma_pnl: float
    vega_pnl: float
    theta_pnl: float
    residual_pnl: float

    inputs: dict[str, float]


def attribute_option_mtm(
    *,
    start: GreeksSnapshot,
    end: GreeksSnapshot,
    qty: float,
    multiplier: float = 100.0,
) -> OptionMtmAttribution:
    """
    Attribute mark-to-market P&L over [start, end] using a first/second-order greek approximation.

    Conventions:
    - option_price is the observed mid/mark in $/share premium units (as quoted).
    - qty is contracts (signed qty is ok; negative implies short).
    - multiplier is contract size (typically 100 for US equity options).
    - theta is per DAY; dt is computed in fractional days.
    - vega is per +1.0 change in IV (i.e., 0.01 IV change contributes vega*0.01).
      If your upstream provides vega per 1 vol-point (1%), scale accordingly before calling.
    """
    q = float(qty)
    mult = float(multiplier)
    if mult <= 0:
        raise ValueError("multiplier must be > 0")

    d_opt = float(end.option_price) - float(start.option_price)
    total = d_opt * q * mult

    dS = float(end.underlying_price) - float(start.underlying_price)
    dIV = float(end.iv) - float(start.iv)
    dt_days = (end.ts - start.ts).total_seconds() / 86400.0

    delta_pnl = float(start.delta) * dS * q * mult
    gamma_pnl = 0.5 * float(start.gamma) * (dS**2) * q * mult
    vega_pnl = float(start.vega) * dIV * q * mult
    theta_pnl = float(start.theta) * dt_days * q * mult

    residual = total - (delta_pnl + gamma_pnl + vega_pnl + theta_pnl)

    return OptionMtmAttribution(
        qty=q,
        multiplier=mult,
        total_mtm_pnl=total,
        delta_pnl=delta_pnl,
        gamma_pnl=gamma_pnl,
        vega_pnl=vega_pnl,
        theta_pnl=theta_pnl,
        residual_pnl=residual,
        inputs={
            "d_option_price": d_opt,
            "dS": dS,
            "dIV": dIV,
            "dt_days": dt_days,
            "start_delta": float(start.delta),
            "start_gamma": float(start.gamma),
            "start_vega": float(start.vega),
            "start_theta": float(start.theta),
        },
    )

