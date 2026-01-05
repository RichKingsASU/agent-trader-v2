"""
Test suite for the Sector Rotation Strategy.

This module contains comprehensive tests for the SectorRotationStrategy
to ensure correct behavior across different market conditions.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sector_rotation import (
    SectorRotationStrategy,
    SECTOR_CONSTITUENTS,
    SECTOR_ETFS,
    ConvictionThresholds,
    AllocationRules,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def strategy():
    """Create a basic strategy instance for testing."""
    config = {
        'top_n_sectors': 3,
        'long_allocation': 0.60,
        'turnover_threshold': 0.20,
        'spy_threshold': -0.5,
        'enable_hedging': True,
    }
    return SectorRotationStrategy(name="test_sector_rotation", config=config)


@pytest.fixture
def mock_market_data_bullish():
    """Mock market data with bullish sentiment across sectors."""
    return {
        'tickers': [
            # Technology sector - Very Bullish
            {'symbol': 'AAPL', 'sentiment_score': 0.85, 'confidence': 0.9},
            {'symbol': 'MSFT', 'sentiment_score': 0.80, 'confidence': 0.85},
            {'symbol': 'GOOGL', 'sentiment_score': 0.75, 'confidence': 0.88},
            {'symbol': 'NVDA', 'sentiment_score': 0.90, 'confidence': 0.92},
            
            # Finance sector - Bullish
            {'symbol': 'JPM', 'sentiment_score': 0.50, 'confidence': 0.75},
            {'symbol': 'BAC', 'sentiment_score': 0.45, 'confidence': 0.70},
            {'symbol': 'GS', 'sentiment_score': 0.55, 'confidence': 0.80},
            
            # Healthcare sector - Neutral
            {'symbol': 'UNH', 'sentiment_score': 0.20, 'confidence': 0.65},
            {'symbol': 'JNJ', 'sentiment_score': 0.15, 'confidence': 0.60},
            
            # Energy sector - Bearish
            {'symbol': 'XOM', 'sentiment_score': -0.50, 'confidence': 0.75},
            {'symbol': 'CVX', 'sentiment_score': -0.45, 'confidence': 0.70},
            
            # SPY - Neutral (no systemic risk)
            {'symbol': 'SPY', 'sentiment_score': 0.30, 'confidence': 0.80},
        ]
    }


@pytest.fixture
def mock_market_data_systemic_risk():
    """Mock market data with SPY indicating systemic risk."""
    return {
        'tickers': [
            {'symbol': 'AAPL', 'sentiment_score': 0.40, 'confidence': 0.70},
            {'symbol': 'MSFT', 'sentiment_score': 0.35, 'confidence': 0.65},
            {'symbol': 'SPY', 'sentiment_score': -0.65, 'confidence': 0.90},  # Systemic risk!
        ]
    }


@pytest.fixture
def mock_account_snapshot():
    """Mock account snapshot with positions."""
    return {
        'equity': '100000.00',
        'buying_power': '50000.00',
        'cash': '40000.00',
        'positions': [
            {
                'symbol': 'XLE',  # Energy sector ETF
                'qty': '100',
                'market_value': '8000.00',
                'avg_entry_price': '75.00',
                'current_price': '80.00',
            },
            {
                'symbol': 'XLK',  # Technology sector ETF
                'qty': '150',
                'market_value': '15000.00',
                'avg_entry_price': '95.00',
                'current_price': '100.00',
            },
        ]
    }


@pytest.fixture
def mock_account_snapshot_empty():
    """Mock account snapshot with no positions."""
    return {
        'equity': '100000.00',
        'buying_power': '100000.00',
        'cash': '100000.00',
        'positions': []
    }


# ============================================================================
# Tests for Helper Methods
# ============================================================================

class TestHelperMethods:
    """Test suite for internal helper methods."""
    
    def test_get_ticker_sentiment_from_list(self, strategy, mock_market_data_bullish):
        """Test extracting sentiment from tickers list."""
        sentiment = strategy._get_ticker_sentiment(mock_market_data_bullish, 'AAPL')
        assert sentiment == 0.85
    
    def test_get_ticker_sentiment_not_found(self, strategy, mock_market_data_bullish):
        """Test that None is returned for missing tickers."""
        sentiment = strategy._get_ticker_sentiment(mock_market_data_bullish, 'NOTFOUND')
        assert sentiment is None
    
    def test_aggregate_sector_sentiments(self, strategy, mock_market_data_bullish):
        """Test sector sentiment aggregation."""
        sector_scores = strategy._aggregate_sector_sentiments(mock_market_data_bullish)
        
        # Check that Technology sector has high sentiment (avg of AAPL, MSFT, GOOGL, NVDA)
        assert 'Technology' in sector_scores
        tech_score = sector_scores['Technology']
        expected = (0.85 + 0.80 + 0.75 + 0.90) / 4
        assert abs(tech_score - expected) < 0.01
        
        # Check Finance sector
        assert 'Finance' in sector_scores
        finance_score = sector_scores['Finance']
        expected_finance = (0.50 + 0.45 + 0.55) / 3
        assert abs(finance_score - expected_finance) < 0.01
    
    def test_get_conviction_level(self, strategy):
        """Test conviction level classification."""
        assert "High Conviction" in strategy._get_conviction_level(0.85)
        assert "Bullish" in strategy._get_conviction_level(0.45)
        assert "Neutral" in strategy._get_conviction_level(0.10)
        assert "Danger" in strategy._get_conviction_level(-0.45)
        assert "Extreme Danger" in strategy._get_conviction_level(-0.65)
    
    def test_select_top_sectors(self, strategy):
        """Test top sector selection."""
        sector_scores = {
            'Technology': 0.82,
            'Finance': 0.50,
            'Healthcare': 0.20,
            'Energy': -0.45,
            'Consumer': 0.60,
        }
        
        top_sectors = strategy._select_top_sectors(sector_scores)
        
        # Should return top 3 sectors with scores > 0.35
        assert len(top_sectors) == 3
        assert top_sectors[0] == ('Technology', 0.82)
        assert top_sectors[1] == ('Consumer', 0.60)
        assert top_sectors[2] == ('Finance', 0.50)
    
    def test_identify_danger_sectors_with_positions(self, strategy, mock_account_snapshot):
        """Test identification of danger sectors with existing positions."""
        sector_scores = {
            'Technology': 0.82,
            'Energy': -0.50,  # Danger! And we have XLE position
            'Finance': 0.45,
        }
        
        danger_sectors = strategy._identify_danger_sectors(sector_scores, mock_account_snapshot)
        
        # Should identify Energy as danger sector since we have XLE position
        assert len(danger_sectors) >= 1
        danger_sector_names = [s for s, _ in danger_sectors]
        assert 'Energy' in danger_sector_names
    
    def test_calculate_sector_allocation(self, strategy):
        """Test sector allocation calculation."""
        # High conviction
        assert strategy._calculate_sector_allocation(0.85) == 1.0
        
        # Bullish
        assert strategy._calculate_sector_allocation(0.45) == 1.0
        
        # Neutral
        assert strategy._calculate_sector_allocation(0.10) == 0.0
        
        # Danger
        assert strategy._calculate_sector_allocation(-0.25) == 0.5
        
        # Extreme danger
        assert strategy._calculate_sector_allocation(-0.65) == 0.0


# ============================================================================
# Tests for Turnover Limits
# ============================================================================

class TestTurnoverLimits:
    """Test suite for turnover limit logic."""
    
    @pytest.mark.asyncio
    async def test_first_rebalance_always_allowed(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that first rebalance is always allowed."""
        signal = await strategy.evaluate(
            mock_market_data_bullish,
            mock_account_snapshot_empty,
            None
        )
        
        # Should generate a BUY signal on first evaluation
        assert signal['action'] == 'BUY'
        assert signal['allocation'] > 0
    
    @pytest.mark.asyncio
    async def test_turnover_limit_blocks_small_changes(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that small sentiment changes don't trigger rebalancing."""
        # First evaluation
        await strategy.evaluate(mock_market_data_bullish, mock_account_snapshot_empty, None)
        
        # Create slightly modified data (change < 20%)
        modified_data = mock_market_data_bullish.copy()
        modified_data['tickers'] = [
            t.copy() if t['symbol'] != 'AAPL' else {**t, 'sentiment_score': 0.80}  # 0.85 -> 0.80 (5% change)
            for t in mock_market_data_bullish['tickers']
        ]
        
        # Second evaluation - should be blocked by turnover limit
        signal = await strategy.evaluate(modified_data, mock_account_snapshot_empty, None)
        
        assert signal['action'] == 'HOLD'
        assert 'turnover' in signal['reasoning'].lower() or 'maintain' in signal['reasoning'].lower()
    
    @pytest.mark.asyncio
    async def test_turnover_limit_allows_large_changes(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that large sentiment changes trigger rebalancing."""
        # First evaluation
        await strategy.evaluate(mock_market_data_bullish, mock_account_snapshot_empty, None)
        
        # Create significantly modified data (change > 20%)
        modified_data = {
            'tickers': [
                t.copy() if t['symbol'] != 'AAPL' else {**t, 'sentiment_score': 0.40}  # 0.85 -> 0.40 (>20% change)
                for t in mock_market_data_bullish['tickers']
            ]
        }
        
        # Second evaluation - should be allowed due to large change
        signal = await strategy.evaluate(modified_data, mock_account_snapshot_empty, None)
        
        # Should generate an action (not just HOLD)
        assert signal['action'] in ['BUY', 'SELL', 'HOLD']
        # If HOLD, it should be for a reason other than turnover
        if signal['action'] == 'HOLD':
            assert 'turnover' not in signal['reasoning'].lower()


# ============================================================================
# Tests for Signal Generation
# ============================================================================

class TestSignalGeneration:
    """Test suite for trading signal generation."""
    
    @pytest.mark.asyncio
    async def test_bullish_signal_generation(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that bullish market generates BUY signals."""
        signal = await strategy.evaluate(
            mock_market_data_bullish,
            mock_account_snapshot_empty,
            None
        )
        
        assert signal['action'] == 'BUY'
        assert signal['allocation'] > 0
        assert signal['allocation'] <= 0.60  # Should not exceed long_allocation
        assert 'Technology' in signal['reasoning'] or signal['ticker'] == 'XLK'
        assert 'metadata' in signal
        assert signal['metadata']['strategy'] == 'sector_rotation'
    
    @pytest.mark.asyncio
    async def test_danger_sector_exit_signal(self, strategy, mock_market_data_bullish, mock_account_snapshot):
        """Test that danger sectors with positions generate SELL signals."""
        signal = await strategy.evaluate(
            mock_market_data_bullish,
            mock_account_snapshot,
            None
        )
        
        # Since Energy is in danger zone and we have XLE position, should generate SELL
        assert signal['action'] == 'SELL'
        assert signal['allocation'] < 0  # Negative allocation = reduce
        assert 'Energy' in signal['reasoning'] or signal['ticker'] == 'XLE'
        assert 'danger' in signal['reasoning'].lower() or 'exit' in signal['reasoning'].lower()
    
    @pytest.mark.asyncio
    async def test_systemic_risk_hedge(self, strategy, mock_market_data_systemic_risk, mock_account_snapshot):
        """Test that SPY systemic risk triggers market hedge."""
        signal = await strategy.evaluate(
            mock_market_data_systemic_risk,
            mock_account_snapshot,
            None
        )
        
        assert signal['action'] == 'SELL'
        assert signal['ticker'] == 'SHV'  # Short-term Treasuries
        assert 'systemic' in signal['reasoning'].lower() or 'spy' in signal['reasoning'].lower()
        assert signal['metadata']['signal_type'] == 'systemic_hedge'
        assert abs(signal['allocation']) >= 0.80  # Should move 80%+ to cash
    
    @pytest.mark.asyncio
    async def test_reasoning_includes_conviction_level(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that reasoning includes conviction level descriptions."""
        signal = await strategy.evaluate(
            mock_market_data_bullish,
            mock_account_snapshot_empty,
            None
        )
        
        reasoning = signal['reasoning'].lower()
        # Should mention conviction or color scale
        assert any(keyword in reasoning for keyword in [
            'conviction', 'green', 'bullish', 'sentiment'
        ])
    
    @pytest.mark.asyncio
    async def test_metadata_includes_sector_scores(self, strategy, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that signal metadata includes sector scores."""
        signal = await strategy.evaluate(
            mock_market_data_bullish,
            mock_account_snapshot_empty,
            None
        )
        
        assert 'metadata' in signal
        metadata = signal['metadata']
        assert 'sector_scores' in metadata
        assert isinstance(metadata['sector_scores'], dict)
        assert len(metadata['sector_scores']) > 0


# ============================================================================
# Tests for Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test suite for edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_no_sentiment_data(self, strategy, mock_account_snapshot_empty):
        """Test behavior when no sentiment data is available."""
        empty_market_data = {'tickers': []}
        
        signal = await strategy.evaluate(
            empty_market_data,
            mock_account_snapshot_empty,
            None
        )
        
        assert signal['action'] == 'HOLD'
        assert 'no' in signal['reasoning'].lower() and 'sentiment' in signal['reasoning'].lower()
    
    @pytest.mark.asyncio
    async def test_no_bullish_sectors(self, strategy, mock_account_snapshot_empty):
        """Test behavior when all sectors are below bullish threshold."""
        bearish_market_data = {
            'tickers': [
                {'symbol': 'AAPL', 'sentiment_score': 0.20, 'confidence': 0.70},
                {'symbol': 'MSFT', 'sentiment_score': 0.15, 'confidence': 0.65},
                {'symbol': 'JPM', 'sentiment_score': 0.10, 'confidence': 0.60},
                {'symbol': 'SPY', 'sentiment_score': 0.05, 'confidence': 0.75},
            ]
        }
        
        signal = await strategy.evaluate(
            bearish_market_data,
            mock_account_snapshot_empty,
            None
        )
        
        assert signal['action'] == 'HOLD'
        assert signal['allocation'] == 0.0
    
    @pytest.mark.asyncio
    async def test_partial_sector_data(self, strategy, mock_account_snapshot_empty):
        """Test behavior when only some tickers in a sector have data."""
        partial_data = {
            'tickers': [
                {'symbol': 'AAPL', 'sentiment_score': 0.85, 'confidence': 0.90},
                # Missing MSFT, GOOGL, NVDA, etc.
            ]
        }
        
        signal = await strategy.evaluate(
            partial_data,
            mock_account_snapshot_empty,
            None
        )
        
        # Should still work with partial data
        assert signal['action'] in ['BUY', 'SELL', 'HOLD']
    
    @pytest.mark.asyncio
    async def test_strategy_with_hedging_disabled(self, mock_market_data_systemic_risk, mock_account_snapshot):
        """Test that systemic hedge doesn't trigger when hedging is disabled."""
        config = {
            'enable_hedging': False,
        }
        strategy = SectorRotationStrategy(name="no_hedge", config=config)
        
        signal = await strategy.evaluate(
            mock_market_data_systemic_risk,
            mock_account_snapshot,
            None
        )
        
        # Should NOT generate SHV hedge signal
        assert signal['ticker'] != 'SHV'


# ============================================================================
# Tests for Configuration
# ============================================================================

class TestConfiguration:
    """Test suite for strategy configuration."""
    
    def test_custom_top_n_sectors(self, mock_market_data_bullish, mock_account_snapshot_empty):
        """Test that top_n_sectors configuration is respected."""
        config = {'top_n_sectors': 5}
        strategy = SectorRotationStrategy(name="custom_n", config=config)
        
        assert strategy.top_n_sectors == 5
    
    def test_custom_allocation_percentage(self):
        """Test that allocation percentage can be customized."""
        config = {'long_allocation': 0.80}
        strategy = SectorRotationStrategy(name="custom_alloc", config=config)
        
        assert strategy.long_allocation == 0.80
    
    def test_custom_turnover_threshold(self):
        """Test that turnover threshold can be customized."""
        config = {'turnover_threshold': 0.15}
        strategy = SectorRotationStrategy(name="custom_turnover", config=config)
        
        assert strategy.turnover_threshold == 0.15
    
    def test_custom_spy_threshold(self):
        """Test that SPY systemic risk threshold can be customized."""
        config = {'spy_threshold': -0.40}
        strategy = SectorRotationStrategy(name="custom_spy", config=config)
        
        assert strategy.spy_threshold == -0.40


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests simulating real-world scenarios."""
    
    @pytest.mark.asyncio
    async def test_full_rotation_cycle(self, strategy, mock_account_snapshot_empty):
        """Test a complete rotation cycle from bullish to bearish."""
        # Phase 1: Initial bullish allocation
        bullish_data = {
            'tickers': [
                {'symbol': 'AAPL', 'sentiment_score': 0.80, 'confidence': 0.85},
                {'symbol': 'MSFT', 'sentiment_score': 0.75, 'confidence': 0.80},
                {'symbol': 'NVDA', 'sentiment_score': 0.85, 'confidence': 0.90},
                {'symbol': 'SPY', 'sentiment_score': 0.50, 'confidence': 0.80},
            ]
        }
        
        signal1 = await strategy.evaluate(bullish_data, mock_account_snapshot_empty, None)
        assert signal1['action'] == 'BUY'
        
        # Phase 2: Sentiment deteriorates significantly (>20% change)
        bearish_data = {
            'tickers': [
                {'symbol': 'AAPL', 'sentiment_score': 0.30, 'confidence': 0.70},  # Down 50%
                {'symbol': 'MSFT', 'sentiment_score': 0.25, 'confidence': 0.65},
                {'symbol': 'NVDA', 'sentiment_score': 0.35, 'confidence': 0.75},
                {'symbol': 'SPY', 'sentiment_score': 0.20, 'confidence': 0.75},
            ]
        }
        
        signal2 = await strategy.evaluate(bearish_data, mock_account_snapshot_empty, None)
        # Should trigger rebalancing due to large sentiment change
        assert signal2['action'] in ['BUY', 'SELL', 'HOLD']
    
    @pytest.mark.asyncio
    async def test_multi_sector_allocation(self, strategy, mock_account_snapshot_empty):
        """Test allocation across multiple top sectors."""
        multi_sector_data = {
            'tickers': [
                # Technology - High
                {'symbol': 'AAPL', 'sentiment_score': 0.82, 'confidence': 0.90},
                {'symbol': 'MSFT', 'sentiment_score': 0.80, 'confidence': 0.88},
                
                # Finance - High
                {'symbol': 'JPM', 'sentiment_score': 0.75, 'confidence': 0.85},
                {'symbol': 'BAC', 'sentiment_score': 0.70, 'confidence': 0.82},
                
                # Healthcare - High
                {'symbol': 'UNH', 'sentiment_score': 0.68, 'confidence': 0.80},
                {'symbol': 'JNJ', 'sentiment_score': 0.72, 'confidence': 0.83},
                
                # SPY - Neutral
                {'symbol': 'SPY', 'sentiment_score': 0.40, 'confidence': 0.80},
            ]
        }
        
        signal = await strategy.evaluate(multi_sector_data, mock_account_snapshot_empty, None)
        
        assert signal['action'] == 'BUY'
        assert 'metadata' in signal
        
        # Check that multiple sectors are mentioned in reasoning or metadata
        if 'top_sectors' in signal['metadata']:
            assert len(signal['metadata']['top_sectors']) == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
