"""
Tests for Smart Risk Circuit Breakers.

This module tests the three circuit breakers:
1. Daily Loss Limit (-2%)
2. VIX Guard (VIX > 30)
3. Concentration Check (> 20%)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock

from backend.risk.circuit_breakers import (
    CircuitBreakerManager,
    CircuitBreakerType,
    CircuitBreakerEvent,
)
from backend.risk.notifications import NotificationService
from backend.ledger.models import LedgerTrade


@pytest.fixture
def mock_db():
    """Mock Firestore client."""
    db = Mock()
    db.collection = Mock(return_value=Mock())
    return db


@pytest.fixture
def mock_notification_service():
    """Mock notification service."""
    service = Mock(spec=NotificationService)
    service.send_notification = AsyncMock()
    return service


@pytest.fixture
def circuit_breaker_manager(mock_db, mock_notification_service):
    """Create a circuit breaker manager for testing."""
    return CircuitBreakerManager(
        db_client=mock_db,
        notification_service=mock_notification_service,
    )


@pytest.fixture
def sample_trades():
    """Create sample trades for testing."""
    now = datetime.now(timezone.utc)
    
    return [
        LedgerTrade(
            tenant_id="test_tenant",
            uid="test_user",
            strategy_id="test_strategy",
            run_id="run_1",
            symbol="SPY",
            side="buy",
            qty=10,
            price=100.0,
            ts=now - timedelta(hours=2),
            fees=1.0,
        ),
        LedgerTrade(
            tenant_id="test_tenant",
            uid="test_user",
            strategy_id="test_strategy",
            run_id="run_1",
            symbol="SPY",
            side="sell",
            qty=10,
            price=95.0,  # $5 loss per share = $50 loss
            ts=now - timedelta(hours=1),
            fees=1.0,
        ),
    ]


class TestDailyLossLimit:
    """Test Daily Loss Limit circuit breaker."""
    
    def test_no_trigger_with_profit(self, circuit_breaker_manager, sample_trades):
        """Test that circuit breaker doesn't trigger with profit."""
        # Modify trade to show profit
        sample_trades[1] = LedgerTrade(
            tenant_id="test_tenant",
            uid="test_user",
            strategy_id="test_strategy",
            run_id="run_1",
            symbol="SPY",
            side="sell",
            qty=10,
            price=105.0,  # $5 profit per share
            ts=datetime.now(timezone.utc),
            fees=1.0,
        )
        
        should_trigger, event = circuit_breaker_manager.check_daily_loss_limit(
            tenant_id="test_tenant",
            user_id="test_user",
            strategy_id="test_strategy",
            trades=sample_trades,
            starting_equity=10000.0,
        )
        
        assert not should_trigger
        assert event is None
    
    def test_trigger_with_2_percent_loss(self, circuit_breaker_manager):
        """Test that circuit breaker triggers with -2% loss."""
        now = datetime.now(timezone.utc)
        
        # Create trades that result in -2% loss
        # Starting equity: $10,000
        # Loss: $200 (2%)
        trades = [
            LedgerTrade(
                tenant_id="test_tenant",
                uid="test_user",
                strategy_id="test_strategy",
                run_id="run_1",
                symbol="SPY",
                side="buy",
                qty=20,
                price=100.0,
                ts=now - timedelta(hours=2),
                fees=0.0,
            ),
            LedgerTrade(
                tenant_id="test_tenant",
                uid="test_user",
                strategy_id="test_strategy",
                run_id="run_1",
                symbol="SPY",
                side="sell",
                qty=20,
                price=90.0,  # $10 loss per share = $200 loss
                ts=now - timedelta(hours=1),
                fees=0.0,
            ),
        ]
        
        should_trigger, event = circuit_breaker_manager.check_daily_loss_limit(
            tenant_id="test_tenant",
            user_id="test_user",
            strategy_id="test_strategy",
            trades=trades,
            starting_equity=10000.0,
        )
        
        assert should_trigger
        assert event is not None
        assert event.breaker_type == CircuitBreakerType.DAILY_LOSS_LIMIT
        assert event.severity == "critical"
        assert event.user_id == "test_user"
    
    def test_no_trigger_with_small_loss(self, circuit_breaker_manager):
        """Test that circuit breaker doesn't trigger with -1% loss."""
        now = datetime.now(timezone.utc)
        
        # Create trades that result in -1% loss
        trades = [
            LedgerTrade(
                tenant_id="test_tenant",
                uid="test_user",
                strategy_id="test_strategy",
                run_id="run_1",
                symbol="SPY",
                side="buy",
                qty=10,
                price=100.0,
                ts=now - timedelta(hours=2),
                fees=0.0,
            ),
            LedgerTrade(
                tenant_id="test_tenant",
                uid="test_user",
                strategy_id="test_strategy",
                run_id="run_1",
                symbol="SPY",
                side="sell",
                qty=10,
                price=99.0,  # $1 loss per share = $100 loss = 1%
                ts=now - timedelta(hours=1),
                fees=0.0,
            ),
        ]
        
        should_trigger, event = circuit_breaker_manager.check_daily_loss_limit(
            tenant_id="test_tenant",
            user_id="test_user",
            strategy_id="test_strategy",
            trades=trades,
            starting_equity=10000.0,
        )
        
        assert not should_trigger
        assert event is None


class TestVIXGuard:
    """Test VIX Guard circuit breaker."""
    
    def test_no_trigger_with_low_vix(self, circuit_breaker_manager):
        """Test that VIX guard doesn't trigger with VIX < 30."""
        # Mock VIX at 25
        circuit_breaker_manager._vix_cache = (25.0, datetime.now(timezone.utc))
        
        adjusted_allocation, event = circuit_breaker_manager.check_vix_guard(
            allocation=1000.0,
        )
        
        assert adjusted_allocation == 1000.0
        assert event is None
    
    def test_trigger_with_high_vix(self, circuit_breaker_manager):
        """Test that VIX guard triggers with VIX > 30."""
        # Mock VIX at 35
        circuit_breaker_manager._vix_cache = (35.0, datetime.now(timezone.utc))
        
        adjusted_allocation, event = circuit_breaker_manager.check_vix_guard(
            allocation=1000.0,
        )
        
        assert adjusted_allocation == 500.0  # 50% reduction
        assert event is not None
        assert event.breaker_type == CircuitBreakerType.VIX_GUARD
        assert event.severity == "warning"
        assert event.metadata["vix_value"] == 35.0
        assert event.metadata["reduction_factor"] == 0.5
    
    def test_no_vix_data_available(self, circuit_breaker_manager):
        """Test that allocation is unchanged when VIX data is unavailable."""
        # No VIX cache
        circuit_breaker_manager._vix_cache = None
        circuit_breaker_manager.db = None  # No DB to fetch from
        
        adjusted_allocation, event = circuit_breaker_manager.check_vix_guard(
            allocation=1000.0,
        )
        
        assert adjusted_allocation == 1000.0
        assert event is None


class TestConcentrationCheck:
    """Test Concentration Check circuit breaker."""
    
    def test_no_trigger_below_threshold(self, circuit_breaker_manager):
        """Test that concentration check doesn't trigger below 20%."""
        positions = {
            "SPY": {
                "symbol": "SPY",
                "qty": 10,
                "current_price": 100.0,  # $1000 value
            }
        }
        
        adjusted_action, event = circuit_breaker_manager.check_concentration(
            ticker="SPY",
            signal_action="BUY",
            positions=positions,
            total_portfolio_value=10000.0,  # 10% concentration
        )
        
        assert adjusted_action == "BUY"
        assert event is None
    
    def test_trigger_above_threshold(self, circuit_breaker_manager):
        """Test that concentration check triggers above 20%."""
        positions = {
            "SPY": {
                "symbol": "SPY",
                "qty": 25,
                "current_price": 100.0,  # $2500 value
            }
        }
        
        adjusted_action, event = circuit_breaker_manager.check_concentration(
            ticker="SPY",
            signal_action="BUY",
            positions=positions,
            total_portfolio_value=10000.0,  # 25% concentration
        )
        
        assert adjusted_action == "HOLD"
        assert event is not None
        assert event.breaker_type == CircuitBreakerType.CONCENTRATION_CHECK
        assert event.severity == "warning"
        assert event.metadata["concentration"] == 0.25
        assert event.metadata["original_action"] == "BUY"
        assert event.metadata["adjusted_action"] == "HOLD"
    
    def test_no_trigger_for_sell_signal(self, circuit_breaker_manager):
        """Test that concentration check only applies to BUY signals."""
        positions = {
            "SPY": {
                "symbol": "SPY",
                "qty": 25,
                "current_price": 100.0,  # $2500 value = 25%
            }
        }
        
        adjusted_action, event = circuit_breaker_manager.check_concentration(
            ticker="SPY",
            signal_action="SELL",
            positions=positions,
            total_portfolio_value=10000.0,
        )
        
        assert adjusted_action == "SELL"
        assert event is None
    
    def test_no_trigger_for_hold_signal(self, circuit_breaker_manager):
        """Test that concentration check only applies to BUY signals."""
        positions = {
            "SPY": {
                "symbol": "SPY",
                "qty": 25,
                "current_price": 100.0,
            }
        }
        
        adjusted_action, event = circuit_breaker_manager.check_concentration(
            ticker="SPY",
            signal_action="HOLD",
            positions=positions,
            total_portfolio_value=10000.0,
        )
        
        assert adjusted_action == "HOLD"
        assert event is None


class TestCircuitBreakerEventHandling:
    """Test circuit breaker event handling."""
    
    @pytest.mark.asyncio
    async def test_handle_circuit_breaker_event(
        self,
        circuit_breaker_manager,
        mock_db,
        mock_notification_service,
    ):
        """Test that circuit breaker events are properly handled."""
        event = CircuitBreakerEvent(
            breaker_type=CircuitBreakerType.DAILY_LOSS_LIMIT,
            timestamp=datetime.now(timezone.utc),
            user_id="test_user",
            tenant_id="test_tenant",
            strategy_id="test_strategy",
            severity="critical",
            message="Test event",
            metadata={"test": "data"},
        )
        
        await circuit_breaker_manager.handle_circuit_breaker_event(event)
        
        # Verify event was stored in Firestore
        assert mock_db.collection.called
        
        # Verify notification was sent
        mock_notification_service.send_notification.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_switch_strategies_to_shadow_mode(
        self,
        circuit_breaker_manager,
        mock_db,
    ):
        """Test switching strategies to shadow mode."""
        # Mock strategy query
        mock_strategy = Mock()
        mock_strategy.id = "strategy_1"
        
        mock_query = Mock()
        mock_query.stream = Mock(return_value=[mock_strategy])
        
        mock_strategies_ref = Mock()
        mock_strategies_ref.where = Mock(return_value=mock_query)
        mock_strategies_ref.document = Mock(return_value=Mock())
        
        # Setup mock DB chain
        mock_users_collection = Mock()
        mock_users_collection.collection = Mock(return_value=mock_strategies_ref)
        
        mock_user_doc = Mock()
        mock_user_doc.collection = Mock(return_value=mock_strategies_ref)
        
        mock_users_ref = Mock()
        mock_users_ref.document = Mock(return_value=mock_user_doc)
        
        mock_tenant_doc = Mock()
        mock_tenant_doc.collection = Mock(return_value=mock_users_ref)
        
        mock_tenants_ref = Mock()
        mock_tenants_ref.document = Mock(return_value=mock_tenant_doc)
        
        mock_db.collection = Mock(return_value=mock_tenants_ref)
        
        await circuit_breaker_manager.switch_strategies_to_shadow_mode(
            tenant_id="test_tenant",
            user_id="test_user",
        )
        
        # Verify the mock was called
        assert mock_db.collection.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
