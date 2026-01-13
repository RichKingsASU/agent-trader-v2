import logging

import pytest

from backend.vnext.risk_guard.interfaces import (
    RiskGuardLimits,
    RiskGuardState,
    RiskGuardTrade,
    evaluate_risk_guard,
)


def _base_trade(**overrides):
    d = dict(
        symbol="AAPL",
        side="buy",
        qty=10.0,
        asset_class="EQUITY",
        contract_multiplier=1.0,
        greeks_gamma=None,
        estimated_price_usd=100.0,
        estimated_notional_usd=1000.0,
    )
    d.update(overrides)
    return RiskGuardTrade(**d)


def _base_state(**overrides):
    d = dict(
        trading_date="2026-01-08",
        daily_pnl_usd=0.0,
        trades_today=0,
        current_position_qty=0.0,
    )
    d.update(overrides)
    return RiskGuardState(**d)


def test_all_limits_none_allows_valid_trade():
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(),
        limits=RiskGuardLimits(),
    )
    assert decision.allowed is True
    assert decision.reject_reason_codes == ()


def test_input_validation_blocks_blank_symbol_and_bad_side_and_non_positive_qty_and_price_and_notional(caplog):
    caplog.set_level(logging.WARNING)
    decision = evaluate_risk_guard(
        trade=_base_trade(
            symbol="  ",
            side="HOLD",
            qty=0,
            estimated_price_usd=0,
            estimated_notional_usd=0,
        ),
        state=_base_state(),
        limits=RiskGuardLimits(),
    )
    assert decision.allowed is False
    # Explicit reasons
    assert set(decision.reject_reason_codes) == {
        "symbol_missing",
        "side_invalid",
        "qty_non_positive",
        "estimated_price_non_positive",
        "estimated_notional_non_positive",
    }
    assert any("risk_guard.blocked" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "daily_pnl,limit,allowed,reason",
    [
        (0.0, 1000.0, True, None),
        (-999.99, 1000.0, True, None),
        (-1000.0, 1000.0, True, None),  # boundary
        (-1000.01, 1000.0, False, "max_daily_loss_exceeded"),
    ],
)
def test_max_daily_loss_rule(daily_pnl, limit, allowed, reason):
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(daily_pnl_usd=daily_pnl),
        limits=RiskGuardLimits(max_daily_loss_usd=limit),
    )
    assert decision.allowed is allowed
    if reason is None:
        assert reason not in decision.reject_reason_codes
    else:
        assert reason in decision.reject_reason_codes


def test_max_daily_loss_requires_daily_pnl_when_enabled():
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(daily_pnl_usd=None),
        limits=RiskGuardLimits(max_daily_loss_usd=100.0),
    )
    assert decision.allowed is False
    assert "daily_pnl_missing" in decision.reject_reason_codes


@pytest.mark.parametrize(
    "notional,limit,allowed",
    [
        (999.0, 1000.0, True),
        (1000.0, 1000.0, True),  # boundary
        (1000.0001, 1000.0, False),
    ],
)
def test_max_order_notional_rule(notional, limit, allowed):
    decision = evaluate_risk_guard(
        trade=_base_trade(estimated_notional_usd=notional),
        state=_base_state(),
        limits=RiskGuardLimits(max_order_notional_usd=limit),
    )
    assert decision.allowed is allowed
    assert ("max_order_notional_exceeded" in decision.reject_reason_codes) is (not allowed)


def test_max_trades_per_day_blocks_when_next_trade_exceeds():
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(trades_today=4),
        limits=RiskGuardLimits(max_trades_per_day=5),
    )
    assert decision.allowed is True

    decision2 = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(trades_today=5),
        limits=RiskGuardLimits(max_trades_per_day=5),
    )
    assert decision2.allowed is False
    assert "max_trades_per_day_exceeded" in decision2.reject_reason_codes


def test_max_trades_per_day_requires_trades_today_when_enabled():
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(trades_today=None),
        limits=RiskGuardLimits(max_trades_per_day=1),
    )
    assert decision.allowed is False
    assert "trades_today_missing" in decision.reject_reason_codes


def test_max_per_symbol_exposure_blocks_increasing_exposure_allows_reducing_exposure():
    # Current: 50 shares @ $100 = $5000 exposure
    # Buy 10 => 60 @ $100 = $6000 projected (block vs $5500)
    decision = evaluate_risk_guard(
        trade=_base_trade(side="buy", qty=10.0, estimated_price_usd=100.0, estimated_notional_usd=1000.0),
        state=_base_state(current_position_qty=50.0),
        limits=RiskGuardLimits(max_per_symbol_exposure_usd=5500.0),
    )
    assert decision.allowed is False
    assert "max_per_symbol_exposure_exceeded" in decision.reject_reason_codes

    # Sell 10 => 40 @ $100 = $4000 projected (allow)
    decision2 = evaluate_risk_guard(
        trade=_base_trade(side="sell", qty=10.0, estimated_price_usd=100.0, estimated_notional_usd=1000.0),
        state=_base_state(current_position_qty=50.0),
        limits=RiskGuardLimits(max_per_symbol_exposure_usd=5500.0),
    )
    assert decision2.allowed is True


def test_max_per_symbol_exposure_handles_shorts():
    # Current short -20, sell 10 more => -30 exposure increases and should be blocked at $2500
    decision = evaluate_risk_guard(
        trade=_base_trade(symbol="TSLA", side="sell", qty=10.0, estimated_price_usd=100.0, estimated_notional_usd=1000.0),
        state=_base_state(current_position_qty=-20.0),
        limits=RiskGuardLimits(max_per_symbol_exposure_usd=2500.0),
    )
    assert decision.allowed is False
    assert "max_per_symbol_exposure_exceeded" in decision.reject_reason_codes

    # Buy 10 reduces short => -10 exposure decreases and should be allowed
    decision2 = evaluate_risk_guard(
        trade=_base_trade(symbol="TSLA", side="buy", qty=10.0, estimated_price_usd=100.0, estimated_notional_usd=1000.0),
        state=_base_state(current_position_qty=-20.0),
        limits=RiskGuardLimits(max_per_symbol_exposure_usd=2500.0),
    )
    assert decision2.allowed is True


def test_max_per_symbol_exposure_requires_current_qty_when_enabled():
    decision = evaluate_risk_guard(
        trade=_base_trade(),
        state=_base_state(current_position_qty=None),
        limits=RiskGuardLimits(max_per_symbol_exposure_usd=100.0),
    )
    assert decision.allowed is False
    assert "current_position_qty_missing" in decision.reject_reason_codes


def test_max_contracts_per_symbol_blocks_when_projected_contracts_exceed_limit():
    # Current: 4 contracts, buy 2 => 6 (block at 5)
    decision = evaluate_risk_guard(
        trade=_base_trade(symbol="SPY240119C00450000", asset_class="OPTIONS", qty=2.0),
        state=_base_state(current_position_qty=4.0),
        limits=RiskGuardLimits(max_contracts_per_symbol=5),
    )
    assert decision.allowed is False
    assert "max_contracts_per_symbol_exceeded" in decision.reject_reason_codes

    # Sell reduces exposure => allow
    decision2 = evaluate_risk_guard(
        trade=_base_trade(symbol="SPY240119C00450000", asset_class="OPTIONS", side="sell", qty=2.0),
        state=_base_state(current_position_qty=4.0),
        limits=RiskGuardLimits(max_contracts_per_symbol=5),
    )
    assert decision2.allowed is True


def test_max_gamma_exposure_blocks_when_incremental_gamma_exceeds_limit_requires_gamma_when_enabled():
    # Missing gamma fails closed when rule enabled
    decision_missing = evaluate_risk_guard(
        trade=_base_trade(symbol="SPY240119C00450000", asset_class="OPTIONS", qty=1.0),
        state=_base_state(),
        limits=RiskGuardLimits(max_gamma_exposure_abs=5.0),
    )
    assert decision_missing.allowed is False
    assert "gamma_missing" in decision_missing.reject_reason_codes

    # gamma=0.08 per contract, qty=1, multiplier=100 => 8.0 (block at 5.0)
    decision_block = evaluate_risk_guard(
        trade=_base_trade(
            symbol="SPY240119C00450000",
            asset_class="OPTIONS",
            qty=1.0,
            contract_multiplier=100.0,
            greeks_gamma=0.08,
        ),
        state=_base_state(),
        limits=RiskGuardLimits(max_gamma_exposure_abs=5.0),
    )
    assert decision_block.allowed is False
    assert "max_gamma_exposure_exceeded" in decision_block.reject_reason_codes

    # Lower gamma is allowed
    decision_ok = evaluate_risk_guard(
        trade=_base_trade(
            symbol="SPY240119C00450000",
            asset_class="OPTIONS",
            qty=1.0,
            contract_multiplier=100.0,
            greeks_gamma=0.02,
        ),
        state=_base_state(),
        limits=RiskGuardLimits(max_gamma_exposure_abs=5.0),
    )
    assert decision_ok.allowed is True

