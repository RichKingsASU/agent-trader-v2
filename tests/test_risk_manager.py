"""
Tests for the Risk Manager kill-switch logic.
"""

import pytest
from unittest.mock import MagicMock, patch

try:
    from functions.risk_manager import (
        AccountSnapshot,
        TradeRequest,
        RiskCheckResult,
        validate_trade_risk,
        _check_high_water_mark,
        _check_trade_size,
        _as_float,
    )
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"Risk manager depends on optional cloud deps (e.g. Firestore): {type(e).__name__}: {e}",
        strict=False,
    )


class TestAsFloat:
    """Tests for _as_float helper function."""
    
    def test_none_returns_zero(self):
        assert _as_float(None) == 0.0
    
    def test_int_conversion(self):
        assert _as_float(42) == 42.0
    
    def test_float_passthrough(self):
        assert _as_float(3.14) == 3.14
    
    def test_string_conversion(self):
        assert _as_float("123.45") == 123.45
    
    def test_empty_string_returns_zero(self):
        assert _as_float("") == 0.0
        assert _as_float("   ") == 0.0
    
    def test_invalid_type_raises_error(self):
        with pytest.raises(TypeError):
            _as_float([1, 2, 3])


class TestCheckHighWaterMark:
    """Tests for high water mark drawdown check."""
    
    def test_no_hwm_set_passes_with_warning(self):
        # When HWM is None, check should pass (but log warning)
        result = _check_high_water_mark(current_equity=50000, high_water_mark=None)
        assert result is None
    
    def test_zero_hwm_passes(self):
        # When HWM is 0 or negative, skip the check
        result = _check_high_water_mark(current_equity=50000, high_water_mark=0)
        assert result is None
    
    def test_equity_above_threshold_passes(self):
        # Current equity is 95% of HWM (within 10% drawdown)
        result = _check_high_water_mark(current_equity=95000, high_water_mark=100000)
        assert result is None
    
    def test_equity_at_threshold_passes(self):
        # Current equity is exactly at 90% of HWM
        result = _check_high_water_mark(current_equity=90000, high_water_mark=100000)
        assert result is None
    
    def test_equity_below_threshold_fails(self):
        # Current equity is 85% of HWM (15% drawdown - exceeds limit)
        result = _check_high_water_mark(current_equity=85000, high_water_mark=100000)
        assert result is not None
        assert "KILL-SWITCH" in result
        assert "15.00%" in result
        assert "85,000" in result
        assert "100,000" in result
    
    def test_severe_drawdown_fails(self):
        # Current equity is 50% of HWM (50% drawdown)
        result = _check_high_water_mark(current_equity=50000, high_water_mark=100000)
        assert result is not None
        assert "KILL-SWITCH" in result
        assert "50.00%" in result


class TestCheckTradeSize:
    """Tests for trade size validation (5% of buying power)."""
    
    def test_zero_buying_power_fails(self):
        result = _check_trade_size(trade_notional=1000, buying_power=0)
        assert result is not None
        assert "KILL-SWITCH" in result
        assert "Buying power is" in result
    
    def test_negative_buying_power_fails(self):
        result = _check_trade_size(trade_notional=1000, buying_power=-5000)
        assert result is not None
        assert "KILL-SWITCH" in result
    
    def test_trade_within_limit_passes(self):
        # Trade is 3% of buying power (within 5% limit)
        result = _check_trade_size(trade_notional=1500, buying_power=50000)
        assert result is None
    
    def test_trade_at_limit_passes(self):
        # Trade is exactly 5% of buying power
        result = _check_trade_size(trade_notional=2500, buying_power=50000)
        assert result is None
    
    def test_trade_exceeds_limit_fails(self):
        # Trade is 10% of buying power (exceeds 5% limit)
        result = _check_trade_size(trade_notional=5000, buying_power=50000)
        assert result is not None
        assert "KILL-SWITCH" in result
        assert "5,000" in result
        assert "10.00%" in result
        assert "2,500" in result  # max allowed
    
    def test_small_trade_large_buying_power_passes(self):
        # Trade is 1% of buying power
        result = _check_trade_size(trade_notional=1000, buying_power=100000)
        assert result is None


class TestValidateTradeRisk:
    """Integration tests for validate_trade_risk function."""
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_valid_trade_passes_all_checks(self, mock_get_hwm):
        # Setup: HWM at 100k, equity at 95k (5% drawdown), trade is 2% of buying power
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is True
        assert result.reason is None
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_equity_below_hwm_rejects_trade(self, mock_get_hwm):
        # Setup: HWM at 100k, equity at 85k (15% drawdown - exceeds limit)
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=85000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is False
        assert "KILL-SWITCH" in result.reason
        assert "15.00%" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_oversized_trade_rejects(self, mock_get_hwm):
        # Setup: Trade is 10% of buying power (exceeds 5% limit)
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="TSLA", side="buy", qty=200, notional_usd=5000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is False
        assert "KILL-SWITCH" in result.reason
        assert "10.00%" in result.reason
        assert "5,000" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_both_checks_fail_returns_first_error(self, mock_get_hwm):
        # Setup: Both HWM check and size check fail
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=80000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=500, notional_usd=10000)
        
        result = validate_trade_risk(account, trade)
        
        # Should return the HWM error first (checked before size)
        assert result.allowed is False
        assert "KILL-SWITCH" in result.reason
        assert "High Water Mark" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_no_hwm_set_only_checks_trade_size(self, mock_get_hwm):
        # Setup: No HWM set, but trade size is valid
        mock_get_hwm.return_value = None
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=2000)
        
        result = validate_trade_risk(account, trade)
        
        # Should pass (HWM check passes with warning, size check passes)
        assert result.allowed is True
        assert result.reason is None
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_negative_equity_rejects(self, mock_get_hwm):
        # Setup: Invalid account snapshot with negative equity
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=-5000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is False
        assert "Invalid account snapshot" in result.reason
        assert "equity is negative" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_negative_buying_power_rejects(self, mock_get_hwm):
        # Setup: Invalid account snapshot with negative buying power
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=-10000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is False
        assert "Invalid account snapshot" in result.reason
        assert "buying_power is negative" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_negative_notional_rejects(self, mock_get_hwm):
        # Setup: Invalid trade request with negative notional
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="sell", qty=100, notional_usd=-1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is False
        assert "Invalid trade request" in result.reason
        assert "notional_usd is negative" in result.reason
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_sell_order_validated_same_as_buy(self, mock_get_hwm):
        # Verify that sell orders are validated the same way as buy orders
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="sell", qty=100, notional_usd=1000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is True
        assert result.reason is None
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_edge_case_exactly_at_limits(self, mock_get_hwm):
        # Test trade that is exactly at all limits
        mock_get_hwm.return_value = 100000
        
        # Equity exactly at 90% of HWM (10% drawdown threshold)
        account = AccountSnapshot(equity=90000, buying_power=50000, cash=25000)
        # Trade exactly at 5% of buying power
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=2500)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is True
        assert result.reason is None
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_tiny_trade_always_passes(self, mock_get_hwm):
        # Very small trade should always pass size check
        mock_get_hwm.return_value = 100000
        
        account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
        trade = TradeRequest(symbol="AAPL", side="buy", qty=1, notional_usd=100)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is True
        assert result.reason is None
    
    @patch('functions.risk_manager._get_high_water_mark')
    def test_large_account_small_trade_passes(self, mock_get_hwm):
        # Test with large account values
        mock_get_hwm.return_value = 10_000_000
        
        account = AccountSnapshot(equity=9_500_000, buying_power=5_000_000, cash=2_500_000)
        trade = TradeRequest(symbol="SPY", side="buy", qty=1000, notional_usd=200_000)
        
        result = validate_trade_risk(account, trade)
        
        assert result.allowed is True
        assert result.reason is None


class TestDataClasses:
    """Tests for data class structures."""
    
    def test_trade_request_creation(self):
        trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=15000)
        assert trade.symbol == "AAPL"
        assert trade.side == "buy"
        assert trade.qty == 100
        assert trade.notional_usd == 15000
    
    def test_account_snapshot_creation(self):
        account = AccountSnapshot(equity=100000, buying_power=50000, cash=25000)
        assert account.equity == 100000
        assert account.buying_power == 50000
        assert account.cash == 25000
    
    def test_risk_check_result_allowed(self):
        result = RiskCheckResult(allowed=True)
        assert result.allowed is True
        assert result.reason is None
    
    def test_risk_check_result_rejected(self):
        result = RiskCheckResult(allowed=False, reason="Test rejection")
        assert result.allowed is False
        assert result.reason == "Test rejection"
