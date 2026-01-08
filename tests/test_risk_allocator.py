import pytest


from backend.risk.risk_allocator import allocate_risk


def test_allocate_risk_is_deterministic_for_same_inputs():
    market_state = {
        "buying_power_usd": 100_000.0,
        "daily_risk_cap_pct": 0.10,  # $10k
        "max_strategy_allocation_pct": 0.50,  # $5k max per strategy
        "current_allocations_usd": {"other": 1000.0},
        "requested_notional_usd": 10_000.0,
        "confidence_scaling": False,
    }
    a1 = allocate_risk("s1", 0.7, market_state)
    a2 = allocate_risk("s1", 0.7, market_state)
    assert a1 == a2


def test_allocate_risk_respects_per_strategy_max_pct():
    market_state = {
        "daily_risk_cap_usd": 10_000.0,
        "max_strategy_allocation_pct": 0.10,  # $1k
        "current_allocations_usd": {},
        "requested_notional_usd": 9_000.0,
    }
    allocated = allocate_risk("s1", 1.0, market_state)
    assert allocated == pytest.approx(1000.0)


def test_allocate_risk_respects_daily_risk_cap_sum():
    market_state = {
        "daily_risk_cap_usd": 10_000.0,
        "max_strategy_allocation_pct": 1.0,
        "current_allocations_usd": {"s_other": 9_500.0},
        "requested_notional_usd": 2_000.0,
    }
    allocated = allocate_risk("s1", 1.0, market_state)
    assert allocated == pytest.approx(500.0)


def test_allocate_risk_fail_closed_without_cap_context():
    # No daily cap and no buying power => allocator returns 0.
    allocated = allocate_risk("s1", 1.0, {"requested_notional_usd": 1000.0})
    assert allocated == 0.0

