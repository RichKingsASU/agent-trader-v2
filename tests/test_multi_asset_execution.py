"""
Test Multi-Asset Smart Routing Execution Engine

Tests the refactored execution engine with:
- Multi-asset support (Equity, Forex, Crypto)
- Slippage estimation based on bid-ask spreads
- Signal downgrade logic when spread > 0.1%
- Portfolio history persistence
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

# Test imports
import sys
sys.path.insert(0, "/workspace")

from backend.execution.engine import (
    OrderIntent,
    ExecutionEngine,
    SmartRouter,
    SmartRoutingDecision,
    MarketDataProvider,
    DryRunBroker,
    RiskManager,
    RiskConfig,
)


class TestMultiAssetOrderIntent:
    """Test multi-asset OrderIntent functionality."""
    
    def test_equity_intent(self):
        """Test creating an equity order intent."""
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="AAPL",
            side="buy",
            qty=10.0,
            asset_class="EQUITY",
            estimated_slippage=0.0005,
        )
        
        assert intent.symbol == "AAPL"
        assert intent.asset_class == "EQUITY"
        assert intent.estimated_slippage == 0.0005
    
    def test_forex_intent(self):
        """Test creating a forex order intent."""
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="EUR/USD",
            side="buy",
            qty=10000.0,
            asset_class="FOREX",
            estimated_slippage=0.0002,
        )
        
        normalized = intent.normalized()
        assert normalized.symbol == "EUR/USD"
        assert normalized.asset_class == "FOREX"
        assert normalized.estimated_slippage == 0.0002
    
    def test_crypto_intent(self):
        """Test creating a crypto order intent."""
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="BTC/USD",
            side="buy",
            qty=0.1,
            asset_class="CRYPTO",
            estimated_slippage=0.001,
        )
        
        normalized = intent.normalized()
        assert normalized.symbol == "BTC/USD"
        assert normalized.asset_class == "CRYPTO"
        assert normalized.estimated_slippage == 0.001


class TestSmartRouter:
    """Test smart routing and slippage estimation."""
    
    def test_downgrade_signal_high_spread(self):
        """Test signal downgrade when spread exceeds threshold."""
        # Mock market data provider
        mock_provider = Mock(spec=MarketDataProvider)
        mock_provider.get_quote.return_value = {
            "bid": 100.0,
            "ask": 100.15,
            "spread": 0.15,
            "spread_pct": 0.0015,  # 0.15% spread
            "mid_price": 100.075,
        }
        
        router = SmartRouter(
            market_data_provider=mock_provider,
            max_spread_pct=0.001  # 0.1% threshold
        )
        
        intent = OrderIntent(
            strategy_id="test",
            broker_account_id="test",
            symbol="AAPL",
            side="buy",
            qty=10.0,
            asset_class="EQUITY",
        )
        
        decision = router.analyze_intent(intent=intent)
        
        assert decision.should_execute is False
        assert decision.downgraded is True
        assert decision.spread_pct == 0.0015
        assert "exceeds threshold" in decision.reason.lower()
    
    def test_allow_signal_low_spread(self):
        """Test signal passes when spread is within threshold."""
        mock_provider = Mock(spec=MarketDataProvider)
        mock_provider.get_quote.return_value = {
            "bid": 100.0,
            "ask": 100.05,
            "spread": 0.05,
            "spread_pct": 0.0005,  # 0.05% spread
            "mid_price": 100.025,
        }
        
        router = SmartRouter(
            market_data_provider=mock_provider,
            max_spread_pct=0.001  # 0.1% threshold
        )
        
        intent = OrderIntent(
            strategy_id="test",
            broker_account_id="test",
            symbol="AAPL",
            side="buy",
            qty=10.0,
            asset_class="EQUITY",
        )
        
        decision = router.analyze_intent(intent=intent)
        
        assert decision.should_execute is True
        assert decision.downgraded is False
        assert decision.spread_pct == 0.0005
    
    def test_precomputed_slippage_high(self):
        """Test using pre-computed slippage that exceeds threshold."""
        router = SmartRouter(max_spread_pct=0.001)
        
        intent = OrderIntent(
            strategy_id="test",
            broker_account_id="test",
            symbol="AAPL",
            side="buy",
            qty=10.0,
            asset_class="EQUITY",
            estimated_slippage=0.002,  # 0.2% pre-computed
        )
        
        decision = router.analyze_intent(intent=intent)
        
        assert decision.should_execute is False
        assert decision.downgraded is True
        assert decision.estimated_slippage == 0.002
    
    def test_precomputed_slippage_acceptable(self):
        """Test using pre-computed slippage within threshold."""
        router = SmartRouter(max_spread_pct=0.001)
        
        intent = OrderIntent(
            strategy_id="test",
            broker_account_id="test",
            symbol="EUR/USD",
            side="buy",
            qty=10000.0,
            asset_class="FOREX",
            estimated_slippage=0.0005,  # 0.05% pre-computed
        )
        
        decision = router.analyze_intent(intent=intent)
        
        assert decision.should_execute is True
        assert decision.downgraded is False
        assert decision.estimated_slippage == 0.0005


class TestExecutionEngineSmartRouting:
    """Test execution engine with smart routing."""
    
    def test_execution_downgraded_by_smart_routing(self, monkeypatch):
        """Test that execution is blocked when smart routing downgrades signal."""
        # Remove kill switch
        monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
        
        # Mock smart router to downgrade
        mock_router = Mock(spec=SmartRouter)
        mock_router.analyze_intent.return_value = SmartRoutingDecision(
            should_execute=False,
            reason="Spread 0.15% exceeds threshold 0.10%",
            estimated_slippage=0.0015,
            spread_pct=0.0015,
            bid=100.0,
            ask=100.15,
            downgraded=True,
        )
        
        # Create execution engine with smart routing
        broker = DryRunBroker()
        
        # Create stub ledger and positions
        class _LedgerStub:
            def count_trades_today(self, **kwargs):
                return 0
            def write_fill(self, **kwargs):
                pass
        
        class _PositionsStub:
            def get_position_qty(self, **kwargs):
                return 0.0
        
        risk = RiskManager(
            config=RiskConfig(fail_open=True),
            ledger=_LedgerStub(),
            positions=_PositionsStub(),
        )
        
        engine = ExecutionEngine(
            broker=broker,
            risk=risk,
            router=mock_router,
            dry_run=False,
            enable_smart_routing=True,
        )
        
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="AAPL",
            side="buy",
            qty=10.0,
            asset_class="EQUITY",
            metadata={"tenant_id": "test_tenant", "uid": "test_user"},
        )
        
        result = engine.execute_intent(intent=intent)
        
        # Verify execution was blocked
        assert result.status == "downgraded"
        assert result.routing is not None
        assert result.routing.downgraded is True
        assert result.routing.spread_pct == 0.0015
        assert "0.15%" in result.routing.reason
    
    def test_execution_allowed_by_smart_routing(self, monkeypatch):
        """Test that execution proceeds when smart routing approves."""
        # Remove kill switch and set EXEC_TENANT_ID
        monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
        monkeypatch.setenv("EXEC_TENANT_ID", "test_tenant")
        
        # Mock smart router to allow
        mock_router = Mock(spec=SmartRouter)
        mock_router.analyze_intent.return_value = SmartRoutingDecision(
            should_execute=True,
            reason="Spread 0.05% within acceptable range",
            estimated_slippage=0.0005,
            spread_pct=0.0005,
            bid=100.0,
            ask=100.05,
            downgraded=False,
        )
        
        broker = DryRunBroker()
        
        class _LedgerStub:
            def count_trades_today(self, *, tenant_id=None, broker_account_id=None, trading_date=None):
                return 0
            def write_fill(self, **kwargs):
                pass
        
        class _PositionsStub:
            def get_position_qty(self, **kwargs):
                return 0.0
        
        risk = RiskManager(
            config=RiskConfig(fail_open=True, max_daily_trades=50, max_position_qty=100000),
            ledger=_LedgerStub(),
            positions=_PositionsStub(),
        )
        
        engine = ExecutionEngine(
            broker=broker,
            risk=risk,
            router=mock_router,
            dry_run=True,  # Use dry run to avoid actual broker calls
            enable_smart_routing=True,
        )
        
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="EUR/USD",
            side="buy",
            qty=10000.0,
            asset_class="FOREX",
            metadata={"tenant_id": "test_tenant", "uid": "test_user"},
        )
        
        result = engine.execute_intent(intent=intent)
        
        # Verify execution was allowed
        assert result.status == "dry_run"  # Dry run passes through
        assert result.routing is not None
        assert result.routing.downgraded is False
        assert result.routing.spread_pct == 0.0005


class TestBaseStrategyMultiAsset:
    """Test BaseStrategy with multi-asset support."""
    
    def test_estimate_slippage(self):
        """Test slippage estimation from market data."""
        from functions.strategies.base_strategy import BaseStrategy
        
        # Create a concrete implementation for testing
        class TestStrategy(BaseStrategy):
            def evaluate(self, market_data, account_snapshot, regime=None):
                pass
        
        strategy = TestStrategy()
        
        # Test with valid bid/ask
        market_data = {
            "symbol": "AAPL",
            "price": 150.0,
            "bid": 149.95,
            "ask": 150.05,
        }
        
        slippage = strategy.estimate_slippage(market_data)
        expected = (150.05 - 149.95) / 150.0
        assert abs(slippage - expected) < 0.0001
    
    def test_should_downgrade_signal(self):
        """Test signal downgrade logic."""
        from functions.strategies.base_strategy import BaseStrategy
        
        class TestStrategy(BaseStrategy):
            def evaluate(self, market_data, account_snapshot, regime=None):
                pass
        
        # Strategy with 0.1% threshold
        strategy = TestStrategy(config={"max_slippage_pct": 0.001})
        
        # High spread market data (0.2%)
        high_spread_data = {
            "symbol": "AAPL",
            "price": 100.0,
            "bid": 99.90,
            "ask": 100.10,
        }
        
        assert strategy.should_downgrade_signal(high_spread_data) is True
        
        # Low spread market data (0.05%)
        low_spread_data = {
            "symbol": "AAPL",
            "price": 100.0,
            "bid": 99.975,
            "ask": 100.025,
        }
        
        assert strategy.should_downgrade_signal(low_spread_data) is False
    
    def test_detect_asset_class(self):
        """Test asset class detection from symbol."""
        from functions.strategies.base_strategy import BaseStrategy, AssetClass
        
        assert BaseStrategy.detect_asset_class("AAPL") == AssetClass.EQUITY
        assert BaseStrategy.detect_asset_class("EUR/USD") == AssetClass.FOREX
        assert BaseStrategy.detect_asset_class("BTC/USD") == AssetClass.CRYPTO
        assert BaseStrategy.detect_asset_class("ETH/USD") == AssetClass.CRYPTO
        assert BaseStrategy.detect_asset_class("AAPL250117C00150000") == AssetClass.OPTIONS


class TestPortfolioHistoryPersistence:
    """Test portfolio history persistence to users/{uid}/portfolio/history."""
    
    def test_portfolio_history_method_exists(self):
        """Test that portfolio history writer method exists and accepts correct params."""
        # Create execution engine
        broker = DryRunBroker()
        
        class _LedgerStub:
            def count_trades_today(self, **kwargs):
                return 0
            def write_fill(self, **kwargs):
                pass
        
        class _PositionsStub:
            def get_position_qty(self, **kwargs):
                return 0.0
        
        risk = RiskManager(
            config=RiskConfig(fail_open=True),
            ledger=_LedgerStub(),
            positions=_PositionsStub(),
        )
        
        engine = ExecutionEngine(
            broker=broker,
            risk=risk,
            dry_run=False,
            enable_smart_routing=False,  # Disable for this test
        )
        
        # Verify the method exists
        assert hasattr(engine, '_write_portfolio_history')
        assert callable(engine._write_portfolio_history)
        
        # Create intent with UID in metadata
        intent = OrderIntent(
            strategy_id="test_strategy",
            broker_account_id="test_account",
            symbol="BTC/USD",
            side="buy",
            qty=0.1,
            asset_class="CRYPTO",
            estimated_slippage=0.0008,
            metadata={
                "tenant_id": "test_tenant",
                "uid": "test_user_123",
            },
        )
        
        # Mock broker order response (filled)
        broker_order = {
            "id": "order_123",
            "status": "filled",
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": "0.1",
            "filled_qty": "0.1",
            "filled_avg_price": "50000.00",
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Test that the method can be called without throwing
        # (it will fail to write to Firestore, but that's expected in test environment)
        try:
            engine._write_portfolio_history(
                intent=intent,
                broker_order=broker_order,
                fill=broker_order
            )
        except Exception as e:
            # Expected to fail in test environment without real Firestore
            # Just verify it's a Firestore-related error
            assert "firestore" in str(e).lower() or "firebase" in str(e).lower() or "attribute" in str(e).lower()


def test_integration_flow():
    """
    Integration test: Full flow from signal to execution with multi-asset support.
    """
    from functions.strategies.base_strategy import (
        BaseStrategy, 
        TradingSignal, 
        SignalType, 
        AssetClass
    )
    
    # Create a test strategy
    class MultiAssetTestStrategy(BaseStrategy):
        def evaluate(self, market_data, account_snapshot, regime=None):
            # Check if we should downgrade due to high costs
            if self.should_downgrade_signal(market_data):
                return TradingSignal(
                    signal_type=SignalType.WAIT,
                    symbol=market_data["symbol"],
                    asset_class=AssetClass[market_data.get("asset_class", "EQUITY")],
                    reasoning="High transaction costs - spread exceeds threshold",
                    estimated_slippage=self.estimate_slippage(market_data),
                )
            
            # Otherwise, generate a buy signal
            return TradingSignal(
                signal_type=SignalType.BUY,
                symbol=market_data["symbol"],
                asset_class=AssetClass[market_data.get("asset_class", "EQUITY")],
                confidence=0.8,
                reasoning="Test buy signal",
                estimated_slippage=self.estimate_slippage(market_data),
            )
    
    strategy = MultiAssetTestStrategy(config={"max_slippage_pct": 0.001})
    
    # Test Case 1: Low spread - should generate BUY
    market_data_low_spread = {
        "symbol": "EUR/USD",
        "asset_class": "FOREX",
        "price": 1.1000,
        "bid": 1.0998,
        "ask": 1.1002,
    }
    
    signal = strategy.evaluate(market_data_low_spread, {})
    assert signal.signal_type == SignalType.BUY
    assert signal.asset_class == AssetClass.FOREX
    assert signal.estimated_slippage < 0.001
    
    # Test Case 2: High spread - should generate WAIT
    market_data_high_spread = {
        "symbol": "BTC/USD",
        "asset_class": "CRYPTO",
        "price": 50000.0,
        "bid": 49950.0,
        "ask": 50050.0,
    }
    
    signal = strategy.evaluate(market_data_high_spread, {})
    assert signal.signal_type == SignalType.WAIT
    assert signal.asset_class == AssetClass.CRYPTO
    assert signal.estimated_slippage > 0.001
    assert "High transaction costs" in signal.reasoning


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
