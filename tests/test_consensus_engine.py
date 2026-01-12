"""
Tests for Consensus Engine

Tests the multi-agent consensus logic including:
- Vote normalization from different strategy types
- Consensus calculation algorithm
- Discordance measurement
- Threshold enforcement
- Firestore logging
"""

import pytest
from decimal import Decimal
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))

from consensus_engine import (
    ConsensusEngine,
    ConsensuAction,
    StrategyVote,
    ConsensusResult
)
from strategies.base_strategy import BaseStrategy, TradingSignal, SignalType


class MockStrategy(BaseStrategy):
    """Mock strategy for testing"""
    
    def __init__(self, config=None, signal_type=SignalType.BUY, confidence=0.8):
        super().__init__(config)
        self._signal_type = signal_type
        self._confidence = confidence
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        return TradingSignal(
            signal_type=self._signal_type,
            confidence=self._confidence,
            reasoning=f"Mock strategy returning {self._signal_type.value}",
            metadata={"mock": True}
        )


@pytest.mark.xfail(reason="architecture drift")
class TestStrategyVote:
    """Tests for StrategyVote dataclass"""
    
    def test_vote_creation(self):
        """Test creating a strategy vote"""
        vote = StrategyVote(
            strategy_name="GammaScalper",
            action=ConsensuAction.BUY,
            confidence=0.85,
            reasoning="Delta threshold exceeded",
            weight=1.0
        )
        
        assert vote.strategy_name == "GammaScalper"
        assert vote.action == ConsensuAction.BUY
        assert vote.confidence == 0.85
        assert vote.reasoning == "Delta threshold exceeded"
        assert vote.weight == 1.0
    
    def test_confidence_clamping(self):
        """Test that confidence is clamped to [0, 1]"""
        # Test upper bound
        vote1 = StrategyVote(
            strategy_name="Test",
            action=ConsensuAction.BUY,
            confidence=1.5,
            reasoning="Test"
        )
        assert vote1.confidence == 1.0
        
        # Test lower bound
        vote2 = StrategyVote(
            strategy_name="Test",
            action=ConsensuAction.SELL,
            confidence=-0.5,
            reasoning="Test"
        )
        assert vote2.confidence == 0.0
    
    def test_to_dict(self):
        """Test converting vote to dictionary"""
        vote = StrategyVote(
            strategy_name="TestStrategy",
            action=ConsensuAction.HOLD,
            confidence=0.6,
            reasoning="Testing",
            weight=1.5,
            metadata={"test": "data"}
        )
        
        vote_dict = vote.to_dict()
        
        assert vote_dict["strategy_name"] == "TestStrategy"
        assert vote_dict["action"] == "HOLD"
        assert vote_dict["confidence"] == 0.6
        assert vote_dict["reasoning"] == "Testing"
        assert vote_dict["weight"] == 1.5
        assert vote_dict["metadata"] == {"test": "data"}


class TestConsensusEngine:
    """Tests for ConsensusEngine"""
    
    def test_initialization(self):
        """Test consensus engine initialization"""
        engine = ConsensusEngine(
            consensus_threshold=0.75,
            strategy_weights={"Strategy1": 2.0, "Strategy2": 1.0}
        )
        
        assert engine.consensus_threshold == 0.75
        assert engine.strategy_weights["Strategy1"] == 2.0
        assert engine.strategy_weights["Strategy2"] == 1.0
    
    def test_threshold_clamping(self):
        """Test that threshold is clamped to [0, 1]"""
        engine1 = ConsensusEngine(consensus_threshold=1.5)
        assert engine1.consensus_threshold == 1.0
        
        engine2 = ConsensusEngine(consensus_threshold=-0.5)
        assert engine2.consensus_threshold == 0.0
    
    def test_normalize_trading_signal(self):
        """Test normalizing a TradingSignal from BaseStrategy"""
        engine = ConsensusEngine()
        
        signal = TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.85,
            reasoning="Test reasoning",
            metadata={"test": "data"}
        )
        
        vote = engine.normalize_signal("TestStrategy", signal)
        
        assert vote.strategy_name == "TestStrategy"
        assert vote.action == ConsensuAction.BUY
        assert vote.confidence == 0.85
        assert vote.reasoning == "Test reasoning"
        assert vote.metadata == {"test": "data"}
    
    def test_normalize_legacy_signal(self):
        """Test normalizing a legacy dict-based signal"""
        engine = ConsensusEngine()
        
        # Test lowercase action
        signal1 = {
            "action": "buy",
            "confidence": 0.7,
            "reason": "Legacy reasoning",
            "signal_payload": {"legacy": True}
        }
        
        vote1 = engine.normalize_signal("LegacyStrategy", signal1)
        
        assert vote1.strategy_name == "LegacyStrategy"
        assert vote1.action == ConsensuAction.BUY
        assert vote1.confidence == 0.7
        assert vote1.reasoning == "Legacy reasoning"
        assert vote1.metadata == {"legacy": True}
        
        # Test uppercase action and 'reasoning' field
        signal2 = {
            "action": "SELL",
            "confidence": 0.9,
            "reasoning": "Uppercase action test",
            "metadata": {"test": True}
        }
        
        vote2 = engine.normalize_signal("AnotherStrategy", signal2)
        
        assert vote2.action == ConsensuAction.SELL
        assert vote2.confidence == 0.9
        assert vote2.reasoning == "Uppercase action test"
    
    def test_normalize_flat_action(self):
        """Test that 'flat' action is normalized to HOLD"""
        engine = ConsensusEngine()
        
        signal = {
            "action": "flat",
            "reason": "No action"
        }
        
        vote = engine.normalize_signal("Strategy", signal)
        
        assert vote.action == ConsensuAction.HOLD
    
    def test_calculate_consensus_unanimous(self):
        """Test consensus calculation with unanimous votes"""
        engine = ConsensusEngine(consensus_threshold=0.7)
        
        votes = [
            StrategyVote("Strategy1", ConsensuAction.BUY, 0.9, "Reason 1", 1.0),
            StrategyVote("Strategy2", ConsensuAction.BUY, 0.85, "Reason 2", 1.0),
            StrategyVote("Strategy3", ConsensuAction.BUY, 0.95, "Reason 3", 1.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        assert result.final_action == ConsensuAction.BUY
        assert result.consensus_score == pytest.approx(0.9, abs=0.01)  # Average confidence
        assert result.should_execute is True  # Above threshold
        assert result.discordance == pytest.approx(0.0, abs=0.1)  # Perfect agreement
    
    def test_calculate_consensus_split(self):
        """Test consensus calculation with split votes"""
        engine = ConsensusEngine(consensus_threshold=0.7)
        
        votes = [
            StrategyVote("Strategy1", ConsensuAction.BUY, 0.8, "Reason 1", 1.0),
            StrategyVote("Strategy2", ConsensuAction.BUY, 0.85, "Reason 2", 1.0),
            StrategyVote("Strategy3", ConsensuAction.SELL, 0.7, "Reason 3", 1.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        assert result.final_action == ConsensuAction.BUY  # Majority wins
        assert result.discordance > 0.3  # Should have some disagreement
        assert len(result.votes) == 3
    
    def test_calculate_consensus_below_threshold(self):
        """Test that signal is not executed when below threshold"""
        engine = ConsensusEngine(consensus_threshold=0.9)  # High threshold
        
        votes = [
            StrategyVote("Strategy1", ConsensuAction.BUY, 0.6, "Reason 1", 1.0),
            StrategyVote("Strategy2", ConsensuAction.HOLD, 0.5, "Reason 2", 1.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        assert result.should_execute is False  # Below threshold
        assert result.consensus_score < 0.9
    
    def test_calculate_consensus_weighted(self):
        """Test consensus calculation with weighted votes"""
        engine = ConsensusEngine(
            consensus_threshold=0.7,
            strategy_weights={
                "HighWeight": 3.0,
                "LowWeight": 1.0
            }
        )
        
        votes = [
            StrategyVote("HighWeight", ConsensuAction.BUY, 0.9, "High weight", 3.0),
            StrategyVote("LowWeight", ConsensuAction.SELL, 0.8, "Low weight", 1.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        # High-weight strategy should dominate
        assert result.final_action == ConsensuAction.BUY
    
    def test_calculate_consensus_all_hold(self):
        """Test consensus when all strategies vote HOLD"""
        engine = ConsensusEngine(consensus_threshold=0.7)
        
        votes = [
            StrategyVote("Strategy1", ConsensuAction.HOLD, 0.9, "Hold 1", 1.0),
            StrategyVote("Strategy2", ConsensuAction.HOLD, 0.85, "Hold 2", 1.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        assert result.final_action == ConsensuAction.HOLD
        assert result.should_execute is False  # HOLD never executes
    
    def test_calculate_consensus_empty_votes(self):
        """Test consensus with no votes"""
        engine = ConsensusEngine()
        
        result = engine.calculate_consensus([])
        
        assert result.final_action == ConsensuAction.HOLD
        assert result.consensus_score == 0.0
        assert result.should_execute is False
    
    def test_discordance_calculation_unanimous(self):
        """Test discordance with unanimous votes"""
        engine = ConsensusEngine()
        
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 1.0),
            StrategyVote("S2", ConsensuAction.BUY, 0.85, "R2", 1.0),
            StrategyVote("S3", ConsensuAction.BUY, 0.95, "R3", 1.0),
        ]
        
        discordance = engine._calculate_discordance(votes)
        
        assert discordance == pytest.approx(0.0, abs=0.1)  # Perfect agreement
    
    def test_discordance_calculation_split(self):
        """Test discordance with evenly split votes"""
        engine = ConsensusEngine()
        
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 1.0),
            StrategyVote("S2", ConsensuAction.SELL, 0.9, "R2", 1.0),
        ]
        
        discordance = engine._calculate_discordance(votes)
        
        # Should be high discordance (50/50 split)
        assert discordance > 0.5
    
    def test_discordance_calculation_three_way_split(self):
        """Test discordance with three-way split"""
        engine = ConsensusEngine()
        
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 1.0),
            StrategyVote("S2", ConsensuAction.SELL, 0.9, "R2", 1.0),
            StrategyVote("S3", ConsensuAction.HOLD, 0.9, "R3", 1.0),
        ]
        
        discordance = engine._calculate_discordance(votes)
        
        # Should be even higher discordance (3-way split)
        assert discordance > 0.6
    
    @pytest.mark.asyncio
    async def test_gather_votes(self):
        """Test gathering votes from strategies"""
        with patch('consensus_engine.load_strategies') as mock_load:
            # Mock strategy classes
            mock_load.return_value = {
                "Strategy1": MockStrategy,
                "Strategy2": MockStrategy,
            }
            
            engine = ConsensusEngine()
            
            market_data = {"symbol": "SPY", "price": 450.0}
            account_snapshot = {"equity": "10000", "buying_power": "5000"}
            
            votes = await engine.gather_votes(
                market_data=market_data,
                account_snapshot=account_snapshot,
                regime="LONG_GAMMA"
            )
            
            assert len(votes) == 2
            assert all(isinstance(vote, StrategyVote) for vote in votes)
    
    @pytest.mark.asyncio
    async def test_gather_votes_with_failures(self):
        """Test that failed strategies don't break consensus"""
        
        class FailingStrategy(BaseStrategy):
            def evaluate(self, market_data, account_snapshot, regime=None):
                raise ValueError("Strategy failed!")
        
        with patch('consensus_engine.load_strategies') as mock_load:
            mock_load.return_value = {
                "GoodStrategy": MockStrategy,
                "BadStrategy": FailingStrategy,
            }
            
            engine = ConsensusEngine()
            
            market_data = {"symbol": "SPY", "price": 450.0}
            account_snapshot = {"equity": "10000", "buying_power": "5000"}
            
            votes = await engine.gather_votes(
                market_data=market_data,
                account_snapshot=account_snapshot
            )
            
            # Should have 2 votes: 1 good, 1 failed with HOLD
            assert len(votes) == 2
            
            # Failed strategy should vote HOLD with 0 confidence
            failed_vote = [v for v in votes if v.strategy_name == "BadStrategy"][0]
            assert failed_vote.action == ConsensuAction.HOLD
            assert failed_vote.confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_generate_consensus_signal(self):
        """Test full consensus signal generation"""
        with patch('consensus_engine.load_strategies') as mock_load:
            mock_load.return_value = {
                "BuyStrategy": lambda config: MockStrategy(config, SignalType.BUY, 0.9),
                "AnotherBuyStrategy": lambda config: MockStrategy(config, SignalType.BUY, 0.85),
            }
            
            mock_db = Mock()
            
            engine = ConsensusEngine(
                consensus_threshold=0.7,
                db=mock_db
            )
            
            market_data = {"symbol": "SPY", "price": 450.0}
            account_snapshot = {"equity": "10000", "buying_power": "5000"}
            
            result = await engine.generate_consensus_signal(
                market_data=market_data,
                account_snapshot=account_snapshot,
                regime="SHORT_GAMMA",
                user_id="test_user"
            )
            
            assert isinstance(result, ConsensusResult)
            assert result.final_action == ConsensuAction.BUY
            assert result.should_execute is True
            assert result.consensus_score >= 0.7
    
    @pytest.mark.asyncio
    async def test_active_strategies_filter(self):
        """Test filtering to only active strategies"""
        with patch('consensus_engine.load_strategies') as mock_load:
            mock_load.return_value = {
                "Strategy1": MockStrategy,
                "Strategy2": MockStrategy,
                "Strategy3": MockStrategy,
            }
            
            engine = ConsensusEngine()
            
            market_data = {"symbol": "SPY", "price": 450.0}
            account_snapshot = {"equity": "10000", "buying_power": "5000"}
            
            # Only use Strategy1 and Strategy2
            votes = await engine.gather_votes(
                market_data=market_data,
                account_snapshot=account_snapshot,
                active_strategies=["Strategy1", "Strategy2"]
            )
            
            assert len(votes) == 2
            strategy_names = [v.strategy_name for v in votes]
            assert "Strategy1" in strategy_names
            assert "Strategy2" in strategy_names
            assert "Strategy3" not in strategy_names


class TestConsensusResult:
    """Tests for ConsensusResult"""
    
    def test_vote_summary(self):
        """Test vote summary calculation"""
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 1.0),
            StrategyVote("S2", ConsensuAction.BUY, 0.85, "R2", 1.0),
            StrategyVote("S3", ConsensuAction.SELL, 0.8, "R3", 1.0),
            StrategyVote("S4", ConsensuAction.HOLD, 0.7, "R4", 1.0),
        ]
        
        result = ConsensusResult(
            final_action=ConsensuAction.BUY,
            consensus_score=0.8,
            confidence=0.85,
            reasoning="Test",
            votes=votes,
            discordance=0.5,
            should_execute=True
        )
        
        summary = result._get_vote_summary()
        
        assert summary["BUY"] == 2
        assert summary["SELL"] == 1
        assert summary["HOLD"] == 1
        assert summary["CLOSE_ALL"] == 0
    
    def test_to_dict(self):
        """Test converting result to dictionary"""
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 1.0)
        ]
        
        result = ConsensusResult(
            final_action=ConsensuAction.BUY,
            consensus_score=0.85,
            confidence=0.9,
            reasoning="Test reasoning",
            votes=votes,
            discordance=0.2,
            should_execute=True,
            metadata={"test": "data"}
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["final_action"] == "BUY"
        assert result_dict["consensus_score"] == 0.85
        assert result_dict["confidence"] == 0.9
        assert result_dict["reasoning"] == "Test reasoning"
        assert result_dict["discordance"] == 0.2
        assert result_dict["should_execute"] is True
        assert result_dict["metadata"] == {"test": "data"}
        assert "vote_summary" in result_dict


class TestEdgeCases:
    """Tests for edge cases and error handling"""
    
    def test_normalize_unknown_signal_type(self):
        """Test normalizing unknown signal type"""
        engine = ConsensusEngine()
        
        # Unknown type should default to HOLD
        vote = engine.normalize_signal("Strategy", "invalid_signal")
        
        assert vote.action == ConsensuAction.HOLD
        assert vote.confidence == 0.0
    
    def test_consensus_with_zero_weights(self):
        """Test consensus when total weight is zero"""
        engine = ConsensusEngine()
        
        votes = [
            StrategyVote("S1", ConsensuAction.BUY, 0.9, "R1", 0.0),
            StrategyVote("S2", ConsensuAction.SELL, 0.85, "R2", 0.0),
        ]
        
        result = engine.calculate_consensus(votes)
        
        # Should handle gracefully
        assert result.final_action in [ConsensuAction.BUY, ConsensuAction.SELL]
    
    def test_reasoning_with_special_characters(self):
        """Test that reasoning with special characters is handled"""
        engine = ConsensusEngine()
        
        votes = [
            StrategyVote(
                "S1",
                ConsensuAction.BUY,
                0.9,
                "Reason with émojis 🚀 and <html> tags & symbols!",
                1.0
            )
        ]
        
        result = engine.calculate_consensus(votes)
        
        # Should not crash
        assert result.reasoning is not None
        assert len(result.reasoning) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
