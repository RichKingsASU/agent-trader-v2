from backend.trading.options.liquidity import (
    OptionLiquidityThresholds,
    evaluate_option_liquidity,
)


def test_option_liquidity_rejects_when_open_interest_below_min() -> None:
    thresholds = OptionLiquidityThresholds(min_open_interest=50, min_volume=10, max_spread_pct=0.20)
    payload = {"bid": 1.00, "ask": 1.10, "open_interest": 12, "volume": 50}
    decision = evaluate_option_liquidity(snapshot_payload=payload, thresholds=thresholds)
    assert decision.allowed is False
    assert decision.reason == "open_interest_below_min"


def test_option_liquidity_rejects_when_volume_below_min() -> None:
    thresholds = OptionLiquidityThresholds(min_open_interest=50, min_volume=10, max_spread_pct=0.20)
    payload = {"bid": 1.00, "ask": 1.10, "open_interest": 150, "volume": 0}
    decision = evaluate_option_liquidity(snapshot_payload=payload, thresholds=thresholds)
    assert decision.allowed is False
    assert decision.reason == "volume_below_min"


def test_option_liquidity_rejects_when_spread_pct_above_max() -> None:
    thresholds = OptionLiquidityThresholds(min_open_interest=50, min_volume=10, max_spread_pct=0.20)
    # mid=1.00, spread=0.60 => 60%
    payload = {"bid": 0.70, "ask": 1.30, "open_interest": 150, "volume": 50}
    decision = evaluate_option_liquidity(snapshot_payload=payload, thresholds=thresholds)
    assert decision.allowed is False
    assert decision.reason == "spread_pct_above_max"


def test_option_liquidity_allows_when_thresholds_met() -> None:
    thresholds = OptionLiquidityThresholds(min_open_interest=50, min_volume=10, max_spread_pct=0.20)
    # mid=1.05, spread=0.10 => ~9.52%
    payload = {"bid": 1.00, "ask": 1.10, "open_interest": 200, "volume": 25}
    decision = evaluate_option_liquidity(snapshot_payload=payload, thresholds=thresholds)
    assert decision.allowed is True
    assert decision.reason == "ok"

