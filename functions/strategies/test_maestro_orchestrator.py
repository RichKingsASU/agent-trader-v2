"""
Unit Tests for MaestroOrchestrator.

Tests the performance-weighted agent allocation system.
"""

import unittest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any

from maestro_orchestrator import MaestroOrchestrator
from base_strategy import SignalType


class TestMaestroOrchestrator(unittest.TestCase):
    """Test suite for MaestroOrchestrator class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'agent_ids': ['WhaleFlowAgent', 'SentimentAgent', 'GammaScalper'],
            'lookback_trades': 50,
            'risk_free_rate': '0.04',
            'min_floor_weight': '0.05',
            'enforce_performance': False
        }
        self.orchestrator = MaestroOrchestrator(config=self.config)
    
    def test_initialization(self):
        """Test MaestroOrchestrator initialization."""
        self.assertEqual(len(self.orchestrator.agent_ids), 3)
        self.assertEqual(self.orchestrator.lookback_trades, 50)
        self.assertEqual(self.orchestrator.risk_free_rate, Decimal('0.04'))
        self.assertEqual(self.orchestrator.min_floor_weight, Decimal('0.05'))
        self.assertFalse(self.orchestrator.enforce_performance)
    
    def test_calculate_daily_returns(self):
        """Test daily return calculation from trades."""
        trades = [
            {
                'trade_id': 't1',
                'realized_pnl': '100',
                'entry_price': '100',
                'quantity': '10'
            },
            {
                'trade_id': 't2',
                'realized_pnl': '-50',
                'entry_price': '200',
                'quantity': '5'
            },
            {
                'trade_id': 't3',
                'realized_pnl': '200',
                'entry_price': '50',
                'quantity': '20'
            }
        ]
        
        returns = self.orchestrator._calculate_daily_returns(trades)
        
        # Expected returns:
        # t1: (100 / (100 * 10)) * 100 = 10%
        # t2: (-50 / (200 * 5)) * 100 = -5%
        # t3: (200 / (50 * 20)) * 100 = 20%
        
        self.assertEqual(len(returns), 3)
        self.assertAlmostEqual(float(returns[0]), 10.0, places=4)
        self.assertAlmostEqual(float(returns[1]), -5.0, places=4)
        self.assertAlmostEqual(float(returns[2]), 20.0, places=4)
    
    def test_calculate_daily_returns_invalid_data(self):
        """Test daily return calculation with invalid data."""
        trades = [
            {
                'trade_id': 't1',
                'realized_pnl': '100',
                'entry_price': '0',  # Zero price should be skipped
                'quantity': '10'
            },
            {
                'trade_id': 't2',
                'realized_pnl': 'invalid',  # Invalid PnL should be skipped
                'entry_price': '100',
                'quantity': '10'
            }
        ]
        
        returns = self.orchestrator._calculate_daily_returns(trades)
        self.assertEqual(len(returns), 0)
    
    def test_calculate_sharpe_ratio(self):
        """Test Sharpe Ratio calculation."""
        # Returns: [10%, 5%, 15%, 8%, 12%]
        returns = [
            Decimal('10'),
            Decimal('5'),
            Decimal('15'),
            Decimal('8'),
            Decimal('12')
        ]
        
        sharpe = self.orchestrator._calculate_sharpe_ratio(returns, Decimal('0.04'))
        
        # Mean return: (10 + 5 + 15 + 8 + 12) / 5 = 10%
        # Daily risk-free: 0.04 / 252 * 100 = 0.0159%
        # Excess return: 10 - 0.0159 = 9.9841%
        # Std dev: ~3.74 (calculated from sample variance)
        # Sharpe: 9.9841 / 3.74 ≈ 2.67
        
        self.assertGreater(sharpe, Decimal('2.0'))
        self.assertLess(sharpe, Decimal('4.0'))
    
    def test_calculate_sharpe_ratio_empty_returns(self):
        """Test Sharpe Ratio with empty returns."""
        returns = []
        sharpe = self.orchestrator._calculate_sharpe_ratio(returns)
        self.assertEqual(sharpe, Decimal('0'))
    
    def test_calculate_sharpe_ratio_single_return(self):
        """Test Sharpe Ratio with single return (insufficient data)."""
        returns = [Decimal('10')]
        sharpe = self.orchestrator._calculate_sharpe_ratio(returns)
        self.assertEqual(sharpe, Decimal('0'))
    
    def test_softmax_normalize_positive_sharpes(self):
        """Test Softmax normalization with all positive Sharpe Ratios."""
        sharpe_ratios = {
            'AgentA': Decimal('2.0'),
            'AgentB': Decimal('1.5'),
            'AgentC': Decimal('1.0')
        }
        
        weights = self.orchestrator._softmax_normalize(sharpe_ratios)
        
        # Verify weights sum to 1.0
        total_weight = sum(weights.values())
        self.assertAlmostEqual(float(total_weight), 1.0, places=6)
        
        # Verify higher Sharpe gets higher weight
        self.assertGreater(weights['AgentA'], weights['AgentB'])
        self.assertGreater(weights['AgentB'], weights['AgentC'])
        
        # All weights should be positive
        for weight in weights.values():
            self.assertGreater(weight, Decimal('0'))
    
    def test_softmax_normalize_negative_sharpes_no_enforcement(self):
        """Test Softmax with negative Sharpes and no performance enforcement."""
        sharpe_ratios = {
            'AgentA': Decimal('2.0'),
            'AgentB': Decimal('-0.5'),
            'AgentC': Decimal('1.0')
        }
        
        # No enforcement: negative Sharpe gets floor weight
        self.orchestrator.enforce_performance = False
        weights = self.orchestrator._softmax_normalize(sharpe_ratios)
        
        # AgentB should have floor weight
        self.assertEqual(weights['AgentB'], self.orchestrator.min_floor_weight)
        
        # Weights should sum to ~1.0
        total_weight = sum(weights.values())
        self.assertAlmostEqual(float(total_weight), 1.0, places=6)
    
    def test_softmax_normalize_negative_sharpes_with_enforcement(self):
        """Test Softmax with negative Sharpes and performance enforcement."""
        sharpe_ratios = {
            'AgentA': Decimal('2.0'),
            'AgentB': Decimal('-0.5'),
            'AgentC': Decimal('1.0')
        }
        
        # With enforcement: negative Sharpe gets 0 weight
        self.orchestrator.enforce_performance = True
        weights = self.orchestrator._softmax_normalize(sharpe_ratios)
        
        # AgentB should have 0 weight
        self.assertEqual(weights['AgentB'], Decimal('0'))
        
        # Remaining weights should sum to 1.0
        total_weight = sum(weights.values())
        self.assertAlmostEqual(float(total_weight), 1.0, places=6)
    
    def test_softmax_normalize_all_negative_sharpes(self):
        """Test Softmax when all agents have negative Sharpes."""
        sharpe_ratios = {
            'AgentA': Decimal('-1.0'),
            'AgentB': Decimal('-0.5'),
            'AgentC': Decimal('-2.0')
        }
        
        # With enforcement: all get 0 weight
        self.orchestrator.enforce_performance = True
        weights = self.orchestrator._softmax_normalize(sharpe_ratios)
        
        for weight in weights.values():
            self.assertEqual(weight, Decimal('0'))
    
    @patch('maestro_orchestrator.firestore')
    def test_fetch_agent_trades(self, mock_firestore):
        """Test fetching agent trades from Firestore."""
        # Mock Firestore client and query
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_doc_ref = MagicMock()
        mock_query = MagicMock()
        
        # Set up mock chain
        mock_db.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc_ref
        mock_doc_ref.collection.return_value = mock_collection
        mock_collection.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        
        # Mock trade documents
        mock_trade1 = Mock()
        mock_trade1.to_dict.return_value = {
            'trade_id': 't1',
            'agent_id': 'WhaleFlowAgent',
            'realized_pnl': '100'
        }
        
        mock_trade2 = Mock()
        mock_trade2.to_dict.return_value = {
            'trade_id': 't2',
            'agent_id': 'WhaleFlowAgent',
            'realized_pnl': '200'
        }
        
        mock_query.stream.return_value = [mock_trade1, mock_trade2]
        
        # Mock firestore.client()
        mock_firestore.client.return_value = mock_db
        mock_firestore.Query = Mock()
        mock_firestore.Query.DESCENDING = 'DESCENDING'
        
        # Test
        self.orchestrator._db = mock_db
        trades = self.orchestrator._fetch_agent_trades('user123', 'WhaleFlowAgent', limit=10)
        
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]['trade_id'], 't1')
        self.assertEqual(trades[1]['trade_id'], 't2')
    
    @patch.object(MaestroOrchestrator, '_fetch_agent_trades')
    def test_calculate_agent_weights(self, mock_fetch):
        """Test end-to-end agent weight calculation."""
        # Mock trade data for each agent
        def fetch_trades_side_effect(user_id, agent_id, limit):
            if agent_id == 'WhaleFlowAgent':
                # Good performance: positive returns
                return [
                    {
                        'trade_id': f't{i}',
                        'agent_id': 'WhaleFlowAgent',
                        'realized_pnl': '100',
                        'entry_price': '100',
                        'quantity': '10'
                    }
                    for i in range(10)
                ]
            elif agent_id == 'SentimentAgent':
                # Medium performance: mixed returns
                return [
                    {
                        'trade_id': f't{i}',
                        'agent_id': 'SentimentAgent',
                        'realized_pnl': '50' if i % 2 == 0 else '-25',
                        'entry_price': '100',
                        'quantity': '10'
                    }
                    for i in range(10)
                ]
            elif agent_id == 'GammaScalper':
                # Poor performance: mostly losses
                return [
                    {
                        'trade_id': f't{i}',
                        'agent_id': 'GammaScalper',
                        'realized_pnl': '-50',
                        'entry_price': '100',
                        'quantity': '10'
                    }
                    for i in range(10)
                ]
            return []
        
        mock_fetch.side_effect = fetch_trades_side_effect
        
        weights = self.orchestrator.calculate_agent_weights('user123')
        
        # Verify weights sum to 1.0
        total_weight = sum(weights.values())
        self.assertAlmostEqual(float(total_weight), 1.0, places=6)
        
        # WhaleFlowAgent should have highest weight (best performance)
        self.assertGreater(weights['WhaleFlowAgent'], weights['SentimentAgent'])
        self.assertGreater(weights['WhaleFlowAgent'], weights['GammaScalper'])
    
    @patch.object(MaestroOrchestrator, 'calculate_agent_weights')
    def test_evaluate(self, mock_calculate):
        """Test evaluate method."""
        # Mock weight calculation
        mock_calculate.return_value = {
            'WhaleFlowAgent': Decimal('0.5'),
            'SentimentAgent': Decimal('0.3'),
            'GammaScalper': Decimal('0.2')
        }
        
        account_snapshot = {
            'user_id': 'user123',
            'equity': '100000'
        }
        
        market_data = {
            'symbol': 'SPY',
            'price': 450.0
        }
        
        signal = self.orchestrator.evaluate(market_data, account_snapshot)
        
        # Verify signal type
        self.assertEqual(signal.signal_type, SignalType.HOLD)
        
        # Verify weights in metadata
        self.assertIn('weights', signal.metadata)
        weights = signal.metadata['weights']
        
        self.assertAlmostEqual(weights['WhaleFlowAgent'], 0.5, places=6)
        self.assertAlmostEqual(weights['SentimentAgent'], 0.3, places=6)
        self.assertAlmostEqual(weights['GammaScalper'], 0.2, places=6)
    
    def test_evaluate_no_user_id(self):
        """Test evaluate with missing user_id."""
        account_snapshot = {
            'equity': '100000'
            # Missing user_id
        }
        
        market_data = {'symbol': 'SPY'}
        
        signal = self.orchestrator.evaluate(market_data, account_snapshot)
        
        self.assertEqual(signal.signal_type, SignalType.HOLD)
        self.assertEqual(signal.confidence, 0.0)
        self.assertIn('error', signal.metadata)


class TestDecimalPrecision(unittest.TestCase):
    """Test that all financial calculations use Decimal."""
    
    def setUp(self):
        """Set up test fixtures."""
        config = {
            'agent_ids': ['AgentA'],
            'risk_free_rate': '0.04'
        }
        self.orchestrator = MaestroOrchestrator(config=config)
    
    def test_risk_free_rate_is_decimal(self):
        """Test that risk_free_rate is stored as Decimal."""
        self.assertIsInstance(self.orchestrator.risk_free_rate, Decimal)
    
    def test_min_floor_weight_is_decimal(self):
        """Test that min_floor_weight is stored as Decimal."""
        self.assertIsInstance(self.orchestrator.min_floor_weight, Decimal)
    
    def test_returns_are_decimal(self):
        """Test that calculated returns are Decimal."""
        trades = [
            {
                'trade_id': 't1',
                'realized_pnl': '100',
                'entry_price': '100',
                'quantity': '10'
            }
        ]
        
        returns = self.orchestrator._calculate_daily_returns(trades)
        
        self.assertTrue(all(isinstance(r, Decimal) for r in returns))
    
    def test_sharpe_ratio_is_decimal(self):
        """Test that Sharpe Ratio is returned as Decimal."""
        returns = [Decimal('10'), Decimal('5'), Decimal('15')]
        sharpe = self.orchestrator._calculate_sharpe_ratio(returns)
        
        self.assertIsInstance(sharpe, Decimal)
    
    def test_weights_are_decimal(self):
        """Test that weights are returned as Decimal."""
        sharpe_ratios = {
            'AgentA': Decimal('2.0'),
            'AgentB': Decimal('1.5')
        }
        
        weights = self.orchestrator._softmax_normalize(sharpe_ratios)
        
        self.assertTrue(all(isinstance(w, Decimal) for w in weights.values()))


if __name__ == '__main__':
    unittest.main()
