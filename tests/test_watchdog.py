"""
Unit tests for Operational Watchdog Agent.

Tests anomaly detection, kill-switch activation, and alert generation.
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock

from functions.utils.watchdog import (
    _detect_losing_streak,
    _detect_rapid_drawdown,
    _detect_market_condition_mismatch,
    _get_recent_trades,
    _activate_kill_switch,
    _send_high_priority_alert,
    _log_watchdog_event,
    _generate_explainability_with_gemini,
    monitor_user_trades,
    AnomalyDetectionResult,
    LOSING_STREAK_THRESHOLD,
    MIN_LOSS_PERCENT,
    RAPID_DRAWDOWN_THRESHOLD,
)


class TestLosingStreakDetection:
    """Test losing streak anomaly detection."""
    
    def test_detect_losing_streak_critical(self):
        """Test that 5 consecutive losing trades trigger critical alert."""
        trades = [
            {
                "id": f"trade_{i}",
                "symbol": "SPY",
                "pnl_percent": "-1.2",
                "current_pnl": "-120.00",
                "created_at": datetime.utcnow(),
            }
            for i in range(5)
        ]
        
        result = _detect_losing_streak(trades)
        
        assert result.anomaly_detected is True
        assert result.anomaly_type == "LOSING_STREAK"
        assert result.severity == "CRITICAL"
        assert result.should_halt_trading is True
        assert result.metadata["consecutive_losses"] == 5
        assert Decimal(result.metadata["total_loss_usd"]) == Decimal("600.00")
    
    def test_detect_losing_streak_no_anomaly(self):
        """Test that mixed wins/losses don't trigger alert."""
        trades = [
            {"id": "trade_1", "pnl_percent": "-1.2", "current_pnl": "-120.00"},
            {"id": "trade_2", "pnl_percent": "0.8", "current_pnl": "80.00"},  # Win breaks streak
            {"id": "trade_3", "pnl_percent": "-0.5", "current_pnl": "-50.00"},
            {"id": "trade_4", "pnl_percent": "-0.3", "current_pnl": "-30.00"},
        ]
        
        result = _detect_losing_streak(trades)
        
        assert result.anomaly_detected is False
    
    def test_detect_losing_streak_insufficient_trades(self):
        """Test that fewer than 5 trades don't trigger alert."""
        trades = [
            {"id": "trade_1", "pnl_percent": "-1.2", "current_pnl": "-120.00"},
            {"id": "trade_2", "pnl_percent": "-0.8", "current_pnl": "-80.00"},
            {"id": "trade_3", "pnl_percent": "-0.5", "current_pnl": "-50.00"},
        ]
        
        result = _detect_losing_streak(trades)
        
        assert result.anomaly_detected is False
    
    def test_detect_losing_streak_small_losses_ignored(self):
        """Test that losses below MIN_LOSS_PERCENT are ignored."""
        trades = [
            {"id": f"trade_{i}", "pnl_percent": "-0.2", "current_pnl": "-20.00"}
            for i in range(10)
        ]
        
        result = _detect_losing_streak(trades)
        
        # Small losses (< 0.5%) don't count toward streak
        assert result.anomaly_detected is False


class TestRapidDrawdownDetection:
    """Test rapid drawdown anomaly detection."""
    
    def test_detect_rapid_drawdown_critical(self):
        """Test that >5% drawdown triggers critical alert."""
        trades = [
            {
                "id": "trade_1",
                "symbol": "SPY",
                "entry_price": "1000.00",
                "quantity": "10",
                "current_pnl": "-520.00",  # 5.2% loss
                "pnl_percent": "-5.2",
            }
        ]
        
        result = _detect_rapid_drawdown(trades)
        
        assert result.anomaly_detected is True
        assert result.anomaly_type == "RAPID_DRAWDOWN"
        assert result.severity == "HIGH"
        assert result.should_halt_trading is True
        assert Decimal(result.metadata["drawdown_percent"]) >= RAPID_DRAWDOWN_THRESHOLD
    
    def test_detect_rapid_drawdown_no_anomaly(self):
        """Test that <5% drawdown doesn't trigger alert."""
        trades = [
            {
                "id": "trade_1",
                "entry_price": "1000.00",
                "quantity": "10",
                "current_pnl": "-300.00",  # 3% loss
                "pnl_percent": "-3.0",
            }
        ]
        
        result = _detect_rapid_drawdown(trades)
        
        assert result.anomaly_detected is False
    
    def test_detect_rapid_drawdown_winning_trades(self):
        """Test that winning trades don't trigger drawdown alert."""
        trades = [
            {
                "id": "trade_1",
                "entry_price": "1000.00",
                "quantity": "10",
                "current_pnl": "500.00",  # Profit
                "pnl_percent": "5.0",
            }
        ]
        
        result = _detect_rapid_drawdown(trades)
        
        assert result.anomaly_detected is False


class TestMarketConditionMismatch:
    """Test market condition mismatch detection."""
    
    @patch('functions.utils.watchdog.firestore')
    def test_detect_mismatch_bearish_market(self, mock_firestore):
        """Test detection of BUY trades during bearish market."""
        # Mock market regime data (Negative GEX = Bearish)
        mock_db = Mock()
        mock_regime_doc = Mock()
        mock_regime_doc.exists = True
        mock_regime_doc.to_dict.return_value = {
            "spy": {"net_gex": "-1200000.00"},
            "market_volatility_bias": "Bearish",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_regime_doc
        
        # Create trades with multiple BUY actions during bearish market
        trades = [
            {"id": f"trade_{i}", "action": "BUY", "symbol": "SPY"}
            for i in range(5)
        ]
        
        result = _detect_market_condition_mismatch(trades, mock_db)
        
        assert result.anomaly_detected is True
        assert result.anomaly_type == "MARKET_CONDITION_MISMATCH"
        assert result.severity == "MEDIUM"
        assert result.should_halt_trading is False  # Warning only
        assert result.metadata["buy_count"] >= 3
    
    @patch('functions.utils.watchdog.firestore')
    def test_no_mismatch_bullish_market(self, mock_firestore):
        """Test that BUY trades during bullish market don't trigger alert."""
        # Mock market regime data (Positive GEX = Bullish)
        mock_db = Mock()
        mock_regime_doc = Mock()
        mock_regime_doc.exists = True
        mock_regime_doc.to_dict.return_value = {
            "spy": {"net_gex": "1200000.00"},
            "market_volatility_bias": "Bullish",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_regime_doc
        
        trades = [
            {"id": f"trade_{i}", "action": "BUY", "symbol": "SPY"}
            for i in range(5)
        ]
        
        result = _detect_market_condition_mismatch(trades, mock_db)
        
        assert result.anomaly_detected is False


class TestKillSwitchActivation:
    """Test kill-switch activation functionality."""
    
    @patch('functions.utils.watchdog.firestore')
    def test_activate_kill_switch_success(self, mock_firestore):
        """Test successful kill-switch activation."""
        mock_db = Mock()
        mock_status_ref = Mock()
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_status_ref
        
        anomaly = AnomalyDetectionResult(
            anomaly_detected=True,
            anomaly_type="LOSING_STREAK",
            severity="CRITICAL",
            description="5 consecutive losing trades",
            should_halt_trading=True
        )
        
        result = _activate_kill_switch(
            db=mock_db,
            user_id="test_user",
            anomaly=anomaly,
            explanation="Agent shut down because..."
        )
        
        assert result["success"] is True
        assert result["trading_enabled"] is False
        mock_status_ref.set.assert_called_once()
        
        # Verify correct data was written
        call_args = mock_status_ref.set.call_args
        data = call_args[0][0]
        assert data["enabled"] is False
        assert data["disabled_by"] == "watchdog"
        assert data["anomaly_type"] == "LOSING_STREAK"


class TestAlertGeneration:
    """Test high-priority alert generation."""
    
    @patch('functions.utils.watchdog.firestore')
    def test_send_high_priority_alert(self, mock_firestore):
        """Test sending high-priority alert to user."""
        mock_db = Mock()
        mock_alerts_ref = Mock()
        mock_alerts_ref.add.return_value = (None, Mock(id="alert_123"))
        mock_db.collection.return_value.document.return_value.collection.return_value = mock_alerts_ref
        
        anomaly = AnomalyDetectionResult(
            anomaly_detected=True,
            anomaly_type="LOSING_STREAK",
            severity="CRITICAL",
            description="5 consecutive losing trades",
            metadata={"consecutive_losses": 5},
            should_halt_trading=True
        )
        
        alert_id = _send_high_priority_alert(
            db=mock_db,
            user_id="test_user",
            anomaly=anomaly,
            explanation="Agent shut down because..."
        )
        
        assert alert_id == "alert_123"
        mock_alerts_ref.add.assert_called_once()
        
        # Verify alert structure
        call_args = mock_alerts_ref.add.call_args
        alert_data = call_args[0][0]
        assert alert_data["type"] == "WATCHDOG_KILL_SWITCH"
        assert alert_data["severity"] == "CRITICAL"
        assert alert_data["priority"] == "HIGH"
        assert alert_data["read"] is False


class TestExplainability:
    """Test AI-powered explainability generation."""
    
    @pytest.mark.asyncio
    @patch('functions.utils.watchdog.vertexai')
    @patch('functions.utils.watchdog.GenerativeModel')
    async def test_generate_explainability_with_gemini(self, mock_model_class, mock_vertexai):
        """Test Gemini AI explainability generation."""
        # Mock Gemini response
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text = "Agent shut down because Strategy X had 5 consecutive losing trades..."
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model
        
        anomaly = AnomalyDetectionResult(
            anomaly_detected=True,
            anomaly_type="LOSING_STREAK",
            severity="CRITICAL",
            description="5 consecutive losing trades",
            should_halt_trading=True
        )
        
        trades = [
            {"id": "trade_1", "symbol": "SPY", "action": "BUY", "pnl_percent": "-1.2"}
        ]
        
        with patch.dict('os.environ', {'GOOGLE_CLOUD_PROJECT': 'test-project'}):
            explanation = await _generate_explainability_with_gemini(
                anomaly=anomaly,
                trades=trades,
                user_id="test_user",
                market_data=None
            )
        
        assert "Agent shut down because" in explanation
        mock_model.generate_content.assert_called_once()


class TestEndToEndMonitoring:
    """Test end-to-end monitoring workflow."""
    
    @pytest.mark.asyncio
    @patch('functions.utils.watchdog._get_recent_trades')
    @patch('functions.utils.watchdog._activate_kill_switch')
    @patch('functions.utils.watchdog._send_high_priority_alert')
    @patch('functions.utils.watchdog._log_watchdog_event')
    @patch('functions.utils.watchdog._generate_explainability_with_gemini')
    async def test_monitor_user_trades_kill_switch_activated(
        self,
        mock_explainability,
        mock_log_event,
        mock_send_alert,
        mock_activate_kill_switch,
        mock_get_trades
    ):
        """Test full monitoring workflow when kill-switch is activated."""
        # Setup mocks
        mock_db = Mock()
        mock_status_doc = Mock()
        mock_status_doc.exists = False
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value = mock_status_doc
        
        # Mock trades (5 losing trades)
        mock_get_trades.return_value = [
            {
                "id": f"trade_{i}",
                "symbol": "SPY",
                "pnl_percent": "-1.2",
                "current_pnl": "-120.00",
            }
            for i in range(5)
        ]
        
        # Mock explainability
        mock_explainability.return_value = "Agent shut down because..."
        
        # Mock kill-switch activation
        mock_activate_kill_switch.return_value = {"success": True}
        
        # Mock alert sending
        mock_send_alert.return_value = "alert_123"
        
        # Mock event logging
        mock_log_event.return_value = "event_456"
        
        # Run monitoring
        result = await monitor_user_trades(db=mock_db, user_id="test_user")
        
        # Verify kill-switch was activated
        assert result["status"] == "KILL_SWITCH_ACTIVATED"
        assert result["anomaly_type"] == "LOSING_STREAK"
        assert "explanation" in result
        
        # Verify all functions were called
        mock_activate_kill_switch.assert_called_once()
        mock_send_alert.assert_called_once()
        mock_log_event.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('functions.utils.watchdog._get_recent_trades')
    async def test_monitor_user_trades_all_clear(self, mock_get_trades):
        """Test monitoring when no anomalies are detected."""
        mock_db = Mock()
        mock_status_doc = Mock()
        mock_status_doc.exists = False
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value = mock_status_doc
        
        # Mock trades (no anomalies)
        mock_get_trades.return_value = [
            {"id": "trade_1", "pnl_percent": "0.5", "current_pnl": "50.00"},
            {"id": "trade_2", "pnl_percent": "0.3", "current_pnl": "30.00"},
        ]
        
        result = await monitor_user_trades(db=mock_db, user_id="test_user")
        
        assert result["status"] == "ALL_CLEAR"
        assert "message" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
