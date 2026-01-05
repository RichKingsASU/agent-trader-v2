from __future__ import annotations

"""
Performance fee calculation and revenue share splits for rented strategies.

This module is intentionally pure-Python (no Firestore dependency) so it's easy to test.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class RevenueShareTerm:
    """
    Minimal term shape used for performance fee calculation.

    Conventions:
    - fee_rate is a decimal rate (e.g. 0.20 for 20%).
    - *_pct fields are decimal fractions (e.g. 0.50 for 50%) and must sum to 1.0.
    """

    fee_rate: float
    creator_pct: float
    platform_pct: float
    user_pct: float


def _req_num(term: Mapping[str, Any], key: str) -> float:
    v = term.get(key)
    if not isinstance(v, (int, float)):
        raise ValueError(f"term[{key}] must be a number")
    return float(v)


def parse_revenue_share_term(term: Optional[Mapping[str, Any]]) -> Optional[RevenueShareTerm]:
    """
    Parse a Firestore-ish dict into a RevenueShareTerm.

    Required keys:
    - fee_rate
    - creator_pct
    - platform_pct
    - user_pct
    """
    if term is None:
        return None

    fee_rate = _req_num(term, "fee_rate")
    creator_pct = _req_num(term, "creator_pct")
    platform_pct = _req_num(term, "platform_pct")
    user_pct = _req_num(term, "user_pct")

    validate_revenue_share_term(
        fee_rate=fee_rate,
        creator_pct=creator_pct,
        platform_pct=platform_pct,
        user_pct=user_pct,
    )
    return RevenueShareTerm(
        fee_rate=fee_rate,
        creator_pct=creator_pct,
        platform_pct=platform_pct,
        user_pct=user_pct,
    )


def validate_revenue_share_term(
    *,
    fee_rate: float,
    creator_pct: float,
    platform_pct: float,
    user_pct: float,
) -> None:
    if fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")
    if creator_pct < 0 or platform_pct < 0 or user_pct < 0:
        raise ValueError("creator_pct/platform_pct/user_pct must be >= 0")

    total = float(creator_pct) + float(platform_pct) + float(user_pct)
    # Use a small tolerance to avoid surprising float issues.
    if abs(total - 1.0) > 1e-9:
        raise ValueError("creator_pct + platform_pct + user_pct must sum to 1.0")


def compute_monthly_performance_fee(*, realized_pnl: float, fee_rate: float) -> float:
    """
    Compute monthly performance fee.

    Spec: realized_pnl × fee_rate
    """
    if fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")
    return float(realized_pnl) * float(fee_rate)


def split_fee_amount(
    *,
    fee_amount: float,
    creator_pct: float,
    platform_pct: float,
    user_pct: float,
) -> dict[str, float]:
    """
    Deterministically split a fee amount by percentages.
    """
    validate_revenue_share_term(
        fee_rate=0.0,
        creator_pct=creator_pct,
        platform_pct=platform_pct,
        user_pct=user_pct,
    )
    amt = float(fee_amount)
    return {
        "creator_amount": amt * float(creator_pct),
        "platform_amount": amt * float(platform_pct),
        "user_amount": amt * float(user_pct),
    }

