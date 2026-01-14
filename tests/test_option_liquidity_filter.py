from backend.execution.option_liquidity import (
    OptionLiquidityThresholds,
    evaluate_option_liquidity,
    extract_option_liquidity_metrics,
)


def test_option_liquidity_allows_when_thresholds_met():
    snap = {
        "openInterest": 250,
        "dailyBar": {"v": 42},
        "latestQuote": {"bp": 1.00, "ap": 1.10, "t": "2026-01-14T15:30:00Z"},
    }
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=100, min_volume=10, max_spread_pct_of_mid=0.15),
    )
    assert allowed is True
    assert reason == "option_liquidity_ok"
    assert details["metrics"]["open_interest"] == 250
    assert details["metrics"]["volume"] == 42


def test_option_liquidity_rejects_low_open_interest():
    snap = {
        "open_interest": 5,
        "dailyBar": {"volume": 100},
        "latestQuote": {"bid_price": 2.0, "ask_price": 2.1},
    }
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, _details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=100, min_volume=1, max_spread_pct_of_mid=0.50),
    )
    assert allowed is False
    assert reason == "option_open_interest_below_min"


def test_option_liquidity_rejects_low_volume():
    snap = {
        "open_interest": 500,
        "daily_bar": {"v": 0},
        "latest_quote": {"bp": 2.0, "ap": 2.02},
    }
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, _details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=1, min_volume=10, max_spread_pct_of_mid=0.50),
    )
    assert allowed is False
    assert reason == "option_volume_below_min"


def test_option_liquidity_rejects_wide_spread_pct():
    snap = {
        "openInterest": 999,
        "dailyBar": {"v": 999},
        "latestQuote": {"bp": 1.00, "ap": 1.60},  # mid=1.30, spread_pct≈46%
    }
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=1, min_volume=1, max_spread_pct_of_mid=0.15),
    )
    assert allowed is False
    assert reason == "option_spread_too_wide"
    assert details["metrics"]["spread_pct"] > 0.15


def test_option_liquidity_fails_closed_when_data_missing():
    snap = {"openInterest": 1000, "dailyBar": {"v": 1000}}  # missing quote
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=1, min_volume=1, max_spread_pct_of_mid=0.99, fail_open=False),
    )
    assert allowed is False
    assert reason == "option_liquidity_data_missing"
    assert "missing" in details


def test_option_liquidity_can_fail_open_when_configured():
    snap = {"openInterest": 1000, "dailyBar": {"v": 1000}}  # missing quote
    metrics = extract_option_liquidity_metrics(snap)
    allowed, reason, details = evaluate_option_liquidity(
        option_symbol="SPY260117C00500000",
        metrics=metrics,
        thresholds=OptionLiquidityThresholds(min_open_interest=1, min_volume=1, max_spread_pct_of_mid=0.99, fail_open=True),
    )
    assert allowed is True
    assert reason == "option_liquidity_data_missing_fail_open"
    assert "missing" in details

