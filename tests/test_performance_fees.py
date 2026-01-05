from __future__ import annotations

import pytest

from backend.marketplace.fees import compute_monthly_performance_fee, split_fee_amount, validate_revenue_share_term


def test_example_month_calculation_realized_pnl_times_fee_rate_and_splits():
    # Example month:
    # - realized_pnl = 10,000.00
    # - fee_rate = 20% => fee = 2,000.00
    # - splits: creator 50%, platform 30%, user 20%
    realized_pnl = 10_000.0
    fee_rate = 0.20
    creator_pct = 0.50
    platform_pct = 0.30
    user_pct = 0.20

    fee_amount = compute_monthly_performance_fee(realized_pnl=realized_pnl, fee_rate=fee_rate)
    assert fee_amount == 2_000.0

    split = split_fee_amount(
        fee_amount=fee_amount,
        creator_pct=creator_pct,
        platform_pct=platform_pct,
        user_pct=user_pct,
    )
    assert split["creator_amount"] == 1_000.0
    assert split["platform_amount"] == 600.0
    assert split["user_amount"] == 400.0


def test_validate_revenue_share_term_requires_sum_to_one():
    with pytest.raises(ValueError):
        validate_revenue_share_term(fee_rate=0.1, creator_pct=0.5, platform_pct=0.3, user_pct=0.3)

