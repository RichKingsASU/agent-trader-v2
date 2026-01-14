"""
Consensus Engine for Multi-Strategy Trading Signals

This module implements an ensemble-based consensus model that aggregates signals
from multiple trading strategies and only executes when there's strong agreement.

Architecture:
- Loads all active strategies dynamically from strategies/ folder
- Normalizes signals from different strategy types (BaseStrategy vs legacy)
- Calculates weighted consensus score
- Only executes trades when consensus > threshold (default 0.7)
- Logs discordance to Firestore for strategy performance analysis
"""

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal

from firebase_admin import firestore
from strategies.base_strategy import BaseStrategy, TradingSignal, SignalType
from strategies.loader import get_strategy_loader

logger = logging.getLogger(__name__)


class ConsensuAction(Enum):
    """Standardized consensus actions"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_ALL = "CLOSE_ALL"


@dataclass
class StrategyVote:
    """
    Represents a single strategy's vote in the consensus.
    
    Attributes:
        strategy_name: Name of the strategy
        action: Voting action (BUY, SELL, HOLD, CLOSE_ALL)
        confidence: Confidence level (0.0 to 1.0)
        reasoning: Explanation for the vote
        weight: Weight of this strategy in consensus (default 1.0)
        metadata: Additional strategy-specific data
    """
    strategy_name: str
    action: ConsensuAction
    confidence: float
    reasoning: str
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        # Ensure confidence is clamped between 0 and 1
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.metadata = self.metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Firestore storage"""
        return {
            "strategy_name": self.strategy_name,
            "action": self.action.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "weight": self.weight,
            "metadata": self.metadata
        }


@dataclass
class ConsensusResult:
    """
    Result of consensus calculation.
    
    Attributes:
        final_action: The consensus action
        consensus_score: Score from 0.0 to 1.0 (1.0 = unanimous agreement)
        confidence: Weighted average confidence
        reasoning: Aggregated reasoning
        votes: List of individual strategy votes
        discordance: Measure of disagreement (0.0 = perfect agreement, 1.0 = maximum disagreement)
        should_execute: Whether to execute based on threshold
    """
    final_action: ConsensuAction
    consensus_score: float
    confidence: float
    reasoning: str
    votes: List[StrategyVote]
    discordance: float
    should_execute: bool
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Firestore storage"""
        return {
            "final_action": self.final_action.value,
            "consensus_score": self.consensus_score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "votes": [vote.to_dict() for vote in self.votes],
            "discordance": self.discordance,
            "should_execute": self.should_execute,
            "metadata": self.metadata or {},
            "vote_summary": self._get_vote_summary()
        }
    
    def _get_vote_summary(self) -> Dict[str, int]:
        """Get count of votes by action"""
        summary = {"BUY": 0, "SELL": 0, "HOLD": 0, "CLOSE_ALL": 0}
        for vote in self.votes:
            summary[vote.action.value] = summary.get(vote.action.value, 0) + 1
        return summary


class ConsensusEngine:
    """
    Consensus Engine that aggregates signals from multiple strategies.
    
    Features:
    - Dynamic strategy loading from strategies/ folder
    - Signal normalization across different strategy types
    - Weighted voting system
    - Configurable consensus threshold
    - Discordance tracking for strategy performance analysis
    """
    
    def __init__(
        self,
        consensus_threshold: float = 0.7,
        strategy_weights: Optional[Dict[str, float]] = None,
        db: Optional[firestore.Client] = None
    ):
        """
        Initialize the Consensus Engine.
        
        Args:
            consensus_threshold: Minimum consensus score required to execute (0.0 to 1.0)
            strategy_weights: Optional custom weights for each strategy {strategy_name: weight}
            db: Firestore client for logging
        """
        self.consensus_threshold = max(0.0, min(1.0, consensus_threshold))
        self.strategy_weights = strategy_weights or {}
        self.db = db
        
        # Load all available strategies
        self.available_strategies = get_strategy_loader(db=self.db).get_all_strategies()
        
        logger.info(
            f"ConsensusEngine initialized: threshold={self.consensus_threshold}, "
            f"available_strategies={list(self.available_strategies.keys())}"
        )
    
    def normalize_signal(
        self,
        strategy_name: str,
        signal: Any,
        strategy_obj: Optional[BaseStrategy] = None
    ) -> StrategyVote:
        """
        Normalize a strategy signal into a standardized StrategyVote.
        
        Handles both:
        - BaseStrategy.evaluate() returning TradingSignal
        - Legacy strategies returning dict with 'action', 'reason', etc.
        
        Args:
            strategy_name: Name of the strategy
            signal: Raw signal from strategy (TradingSignal or dict)
            strategy_obj: Optional strategy instance for additional context
        
        Returns:
            StrategyVote with normalized data
        """
        try:
            # Get strategy weight
            weight = self.strategy_weights.get(strategy_name, 1.0)
            
            # Handle TradingSignal objects from BaseStrategy
            if isinstance(signal, TradingSignal):
                return StrategyVote(
                    strategy_name=strategy_name,
                    action=ConsensuAction(signal.signal_type.value),
                    confidence=signal.confidence,
                    reasoning=signal.reasoning,
                    weight=weight,
                    metadata=signal.metadata
                )
            
            # Handle dict-based signals (legacy format)
            elif isinstance(signal, dict):
                # Map legacy actions to ConsensuAction
                action_map = {
                    "buy": ConsensuAction.BUY,
                    "sell": ConsensuAction.SELL,
                    "flat": ConsensuAction.HOLD,
                    "hold": ConsensuAction.HOLD,
                    "BUY": ConsensuAction.BUY,
                    "SELL": ConsensuAction.SELL,
                    "HOLD": ConsensuAction.HOLD,
                    "CLOSE_ALL": ConsensuAction.CLOSE_ALL,
                }
                
                raw_action = signal.get("action", "HOLD")
                action = action_map.get(raw_action, ConsensuAction.HOLD)
                
                # Extract confidence (default to 0.5 if not provided)
                confidence = signal.get("confidence", 0.5)
                
                # Extract reasoning
                reasoning = signal.get("reason", signal.get("reasoning", "No reason provided"))
                
                # Extract metadata
                metadata = signal.get("signal_payload", signal.get("metadata", {}))
                
                return StrategyVote(
                    strategy_name=strategy_name,
                    action=action,
                    confidence=confidence,
                    reasoning=reasoning,
                    weight=weight,
                    metadata=metadata
                )
            
            else:
                logger.warning(f"Unknown signal type from {strategy_name}: {type(signal)}")
                return StrategyVote(
                    strategy_name=strategy_name,
                    action=ConsensuAction.HOLD,
                    confidence=0.0,
                    reasoning="Unknown signal type",
                    weight=weight
                )
        
        except Exception as e:
            logger.exception(f"Error normalizing signal from {strategy_name}: {e}")
            return StrategyVote(
                strategy_name=strategy_name,
                action=ConsensuAction.HOLD,
                confidence=0.0,
                reasoning=f"Error normalizing signal: {str(e)}",
                weight=1.0
            )
    
    def calculate_consensus(self, votes: List[StrategyVote]) -> ConsensusResult:
        """
        Calculate consensus from a list of strategy votes.
        
        Algorithm:
        1. Group votes by action
        2. Calculate weighted score for each action
        3. Select action with highest weighted score
        4. Calculate consensus score (0.0 to 1.0)
        5. Calculate discordance (disagreement measure)
        6. Determine if should execute based on threshold
        
        Args:
            votes: List of StrategyVote objects
        
        Returns:
            ConsensusResult with final decision and analysis
        """
        if not votes:
            return ConsensusResult(
                final_action=ConsensuAction.HOLD,
                consensus_score=0.0,
                confidence=0.0,
                reasoning="No votes received from strategies",
                votes=[],
                discordance=0.0,
                should_execute=False
            )
        
        # Calculate weighted scores for each action
        action_scores: Dict[ConsensuAction, float] = {}
        action_confidences: Dict[ConsensuAction, List[float]] = {}
        total_weight = sum(vote.weight for vote in votes)
        
        for vote in votes:
            # Weighted score = weight * confidence
            score = vote.weight * vote.confidence
            action_scores[vote.action] = action_scores.get(vote.action, 0.0) + score
            
            if vote.action not in action_confidences:
                action_confidences[vote.action] = []
            action_confidences[vote.action].append(vote.confidence)
        
        # Normalize scores by total weight
        if total_weight > 0:
            for action in action_scores:
                action_scores[action] /= total_weight
        
        # Select action with highest weighted score
        if not action_scores:
            final_action = ConsensuAction.HOLD
            consensus_score = 0.0
        else:
            final_action = max(action_scores, key=action_scores.get)
            consensus_score = action_scores[final_action]
        
        # Calculate weighted average confidence for the winning action
        if final_action in action_confidences:
            confidences = action_confidences[final_action]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        else:
            avg_confidence = 0.0
        
        # Calculate discordance (entropy-based measure of disagreement)
        discordance = self._calculate_discordance(votes)
        
        # Determine if should execute
        should_execute = (
            consensus_score >= self.consensus_threshold and
            final_action != ConsensuAction.HOLD
        )
        
        # Build reasoning
        reasoning = self._build_consensus_reasoning(
            votes, final_action, consensus_score, discordance
        )
        
        return ConsensusResult(
            final_action=final_action,
            consensus_score=consensus_score,
            confidence=avg_confidence,
            reasoning=reasoning,
            votes=votes,
            discordance=discordance,
            should_execute=should_execute,
            metadata={
                "action_scores": {action.value: score for action, score in action_scores.items()},
                "total_strategies": len(votes),
                "threshold": self.consensus_threshold
            }
        )
    
    def _calculate_discordance(self, votes: List[StrategyVote]) -> float:
        """
        Calculate discordance (disagreement) among strategies.
        
        Uses normalized entropy as a measure of disagreement:
        - 0.0 = Perfect agreement (all votes same)
        - 1.0 = Maximum disagreement (votes evenly distributed)
        
        Args:
            votes: List of strategy votes
        
        Returns:
            Discordance score between 0.0 and 1.0
        """
        import math
        
        if not votes:
            return 0.0
        
        # Count votes by action
        action_counts: Dict[str, int] = {}
        for vote in votes:
            action_counts[vote.action.value] = action_counts.get(vote.action.value, 0) + 1
        
        # Calculate Shannon entropy
        total = len(votes)
        entropy = 0.0
        for count in action_counts.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        
        # Normalize entropy to [0, 1]
        # Max entropy occurs when votes are evenly distributed across all possible actions
        num_unique_actions = len(action_counts)
        max_entropy = math.log2(num_unique_actions) if num_unique_actions > 1 else 0.0
        normalized_discordance = entropy / max_entropy if max_entropy > 0 else 0.0
        
        return min(1.0, normalized_discordance)
    
    def _build_consensus_reasoning(
        self,
        votes: List[StrategyVote],
        final_action: ConsensuAction,
        consensus_score: float,
        discordance: float
    ) -> str:
        """
        Build human-readable reasoning for the consensus decision.
        
        Args:
            votes: List of all votes
            final_action: The consensus action
            consensus_score: Consensus score
            discordance: Discordance measure
        
        Returns:
            Human-readable reasoning string
        """
        # Count votes by action
        vote_counts = {}
        for vote in votes:
            vote_counts[vote.action.value] = vote_counts.get(vote.action.value, 0) + 1
        
        # Build vote summary
        vote_summary = ", ".join([f"{action}: {count}" for action, count in vote_counts.items()])
        
        # List strategies that agree with consensus
        agreeing_strategies = [
            vote.strategy_name for vote in votes if vote.action == final_action
        ]
        
        # List strategies that disagree
        disagreeing_strategies = [
            f"{vote.strategy_name} ({vote.action.value})"
            for vote in votes if vote.action != final_action
        ]
        
        reasoning_parts = [
            f"Consensus: {final_action.value} with score {consensus_score:.2f} (threshold: {self.consensus_threshold:.2f})",
            f"Vote Distribution: {vote_summary}",
            f"Agreement: {len(agreeing_strategies)}/{len(votes)} strategies support {final_action.value}",
        ]
        
        if agreeing_strategies:
            reasoning_parts.append(f"Supporting: {', '.join(agreeing_strategies)}")
        
        if disagreeing_strategies:
            reasoning_parts.append(f"Dissenting: {', '.join(disagreeing_strategies)}")
        
        if discordance > 0.5:
            reasoning_parts.append(
                f"⚠️ HIGH DISCORDANCE ({discordance:.2f}): Significant disagreement among strategies"
            )
        
        return " | ".join(reasoning_parts)
    
    async def gather_votes(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None,
        active_strategies: Optional[List[str]] = None
    ) -> List[StrategyVote]:
        """
        Gather votes from all active strategies.
        
        Args:
            market_data: Current market data
            account_snapshot: Account snapshot
            regime: Optional market regime
            active_strategies: Optional list of strategy names to use (defaults to all)
        
        Returns:
            List of StrategyVote objects
        """
        votes = []
        
        # Determine which strategies to evaluate
        if active_strategies:
            strategies_to_evaluate = {
                name: cls for name, cls in self.available_strategies.items()
                if name in active_strategies
            }
        else:
            strategies_to_evaluate = self.available_strategies
        
        logger.info(f"Gathering votes from {len(strategies_to_evaluate)} strategies")
        
        for strategy_name, strategy_cls in strategies_to_evaluate.items():
            try:
                # Instantiate strategy
                strategy = strategy_cls(config={})
                
                # Evaluate strategy
                logger.debug(f"Evaluating {strategy_name}...")
                signal = strategy.evaluate(
                    market_data=market_data,
                    account_snapshot=account_snapshot,
                    regime=regime
                )
                
                # Normalize signal to vote
                vote = self.normalize_signal(strategy_name, signal, strategy)
                votes.append(vote)
                
                logger.info(
                    f"✓ {strategy_name}: {vote.action.value} "
                    f"(confidence={vote.confidence:.2f}, weight={vote.weight})"
                )
                
            except Exception as e:
                logger.exception(f"Error evaluating strategy {strategy_name}: {e}")
                # Add a HOLD vote with zero confidence for failed strategies
                votes.append(StrategyVote(
                    strategy_name=strategy_name,
                    action=ConsensuAction.HOLD,
                    confidence=0.0,
                    reasoning=f"Strategy evaluation failed: {str(e)}",
                    weight=self.strategy_weights.get(strategy_name, 1.0)
                ))
        
        return votes
    
    async def generate_consensus_signal(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None,
        active_strategies: Optional[List[str]] = None,
        user_id: Optional[str] = None
    ) -> ConsensusResult:
        """
        Generate a consensus trading signal from all active strategies.
        
        This is the main entry point for the consensus engine.
        
        Args:
            market_data: Current market data
            account_snapshot: Account snapshot
            regime: Optional market regime from GEX engine
            active_strategies: Optional list of strategy names to use
            user_id: Optional user ID for logging
        
        Returns:
            ConsensusResult with final decision
        """
        logger.info("=== CONSENSUS ENGINE: Generating Signal ===")
        
        # Step 1: Gather votes from all strategies
        votes = await self.gather_votes(
            market_data=market_data,
            account_snapshot=account_snapshot,
            regime=regime,
            active_strategies=active_strategies
        )
        
        # Step 2: Calculate consensus
        result = self.calculate_consensus(votes)
        
        # Step 3: Log to Firestore
        if self.db:
            await self._log_consensus_to_firestore(result, user_id)
        
        # Step 4: Log discordance if high
        if result.discordance > 0.5:
            logger.warning(
                f"⚠️ HIGH DISCORDANCE DETECTED: {result.discordance:.2f} | "
                f"Strategies are in significant disagreement"
            )
            if self.db:
                await self._log_discordance_to_firestore(result, user_id)
        
        logger.info(
            f"=== CONSENSUS RESULT: {result.final_action.value} "
            f"(score={result.consensus_score:.2f}, "
            f"should_execute={result.should_execute}) ==="
        )
        
        return result
    
    async def _log_consensus_to_firestore(
        self,
        result: ConsensusResult,
        user_id: Optional[str] = None
    ) -> None:
        """
        Log consensus result to Firestore for historical analysis.
        
        Args:
            result: ConsensusResult to log
            user_id: Optional user ID for user-scoped logging
        """
        try:
            consensus_doc = {
                **result.to_dict(),
                "timestamp": firestore.SERVER_TIMESTAMP,
                "user_id": user_id or "system"
            }
            
            # Log to consensusSignals collection
            self.db.collection("consensusSignals").add(consensus_doc)
            
            logger.debug("Consensus result logged to Firestore")
            
        except Exception as e:
            logger.exception(f"Error logging consensus to Firestore: {e}")
    
    async def _log_discordance_to_firestore(
        self,
        result: ConsensusResult,
        user_id: Optional[str] = None
    ) -> None:
        """
        Log high discordance events to Firestore for strategy analysis.
        
        This helps identify:
        - Which strategies are frequently disagreeing
        - Patterns in market conditions that cause disagreement
        - Strategies that may need tuning
        
        Args:
            result: ConsensusResult with high discordance
            user_id: Optional user ID
        """
        try:
            discordance_doc = {
                "discordance": result.discordance,
                "final_action": result.final_action.value,
                "consensus_score": result.consensus_score,
                "vote_summary": result._get_vote_summary(),
                "votes": [vote.to_dict() for vote in result.votes],
                "timestamp": firestore.SERVER_TIMESTAMP,
                "user_id": user_id or "system",
                "threshold": self.consensus_threshold,
                "should_execute": result.should_execute
            }
            
            # Log to discordanceEvents collection
            self.db.collection("discordanceEvents").add(discordance_doc)
            
            logger.warning(
                f"High discordance event logged to Firestore: {result.discordance:.2f}"
            )
            
        except Exception as e:
            logger.exception(f"Error logging discordance to Firestore: {e}")
