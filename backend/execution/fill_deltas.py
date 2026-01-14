from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True, slots=True)
class FillDelta:
    """
    Delta fill derived from a cumulative (qty, avg_price) snapshot.
    """

    delta_qty: float
    delta_price: float
    cum_qty: float
    cum_avg_price: float
    prev_qty: float
    prev_notional: float
    cum_notional: float


def compute_delta_from_cumulative(
    *,
    cum_qty: float,
    cum_avg_price: float,
    prev_fills: Iterable[Tuple[float, float]],
) -> FillDelta:
    """
    Compute a delta fill that makes totals consistent with a cumulative snapshot.

    Broker order snapshots commonly report:
    - cum_qty: cumulative filled quantity
    - cum_avg_price: cumulative average fill price

    Given previously-recorded delta fills (qty, price), we compute:
      prev_qty = sum(qty)
      prev_notional = sum(qty * price)
      cum_notional = cum_qty * cum_avg_price
      delta_qty = cum_qty - prev_qty
      delta_price = (cum_notional - prev_notional) / delta_qty

    This prevents double counting on partial-fill updates while preserving the broker-reported
    cumulative average price.
    """
    cq = float(cum_qty or 0.0)
    cap = float(cum_avg_price or 0.0)
    if cq < 0:
        cq = 0.0
    if cap < 0:
        cap = 0.0

    prev_qty = 0.0
    prev_notional = 0.0
    for q, p in prev_fills:
        try:
            q0 = float(q or 0.0)
            p0 = float(p or 0.0)
        except Exception:
            continue
        if q0 > 0 and p0 > 0:
            prev_qty += q0
            prev_notional += q0 * p0

    cum_notional = cq * cap
    delta_qty = cq - prev_qty
    if delta_qty <= 0:
        return FillDelta(
            delta_qty=0.0,
            delta_price=0.0,
            cum_qty=cq,
            cum_avg_price=cap,
            prev_qty=prev_qty,
            prev_notional=prev_notional,
            cum_notional=cum_notional,
        )

    delta_notional = cum_notional - prev_notional
    # Clamp small negative due to rounding drift.
    if delta_notional <= 0:
        delta_notional = delta_qty * cap
    delta_price = (delta_notional / delta_qty) if delta_qty > 0 else cap
    if delta_price <= 0:
        delta_price = cap

    return FillDelta(
        delta_qty=float(delta_qty),
        delta_price=float(delta_price),
        cum_qty=cq,
        cum_avg_price=cap,
        prev_qty=float(prev_qty),
        prev_notional=float(prev_notional),
        cum_notional=float(cum_notional),
    )

