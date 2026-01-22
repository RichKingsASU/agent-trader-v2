"""
MaestroOrchestrator: Dynamic Portfolio Weighting Based on Agent Performance.

This module implements a performance-weighted orchestrator that dynamically adjusts
capital allocation across specialized trading agents based on their historical Sharpe Ratios.

All financial calculations use decimal.Decimal for precision.
"""

from decimal import Decimal, getcontext, InvalidOperation
from typing import Dict, Any, List, Optional
from collections import defaultdict
import logging
import math

from firebase_admin import firestore

from .base_strategy import BaseStrategy, TradingSignal, SignalType

# Set decimal precision for financial calculations
getcontext().prec = 28

logger = logging.getLogger(__name__)


class MaestroOrchestrator(BaseStrategy):
    """
    Dynamic agent weight orchestrator based on historical performance.
    
    Queries tradeJournal for each specialized agent (e.g., 'WhaleFlowAgent', 'SentimentAgent'),
    calculates Sharpe Ratios, and outputs capital allocation weights using Softmax normalization.
    
    Configuration:
        - agent_ids: List[str] - Agent identifiers to track (e.g., ['WhaleFlowAgent', 'SentimentAgent'])
        - lookback_trades: int - Number of recent trades to analyze per agent (default: 100)
        - risk_free_rate: Decimal - Annual risk-free rate for Sharpe calculation (default: 0.04)
        - min_floor_weight: Decimal - Minimum weight for negative Sharpe agents (default: 0.05)
        - enforce_performance: bool - If True, set weight to 0.0 for negative Sharpe (default: False)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize MaestroOrchestrator with configuration.
        
        Args:
            config: Configuration dictionary with optional overrides
        """
        super().__init__(config)
        
        # Load configuration with defaults
        self.agent_ids: List[str] = self.config.get('agent_ids', [
            'WhaleFlowAgent',
            'SentimentAgent',
            'GammaScalper',
            'SectorRotation'
        ])
        
        self.lookback_trades: int = self.config.get('lookback_trades', 100)
        self.risk_free_rate: Decimal = Decimal(str(self.config.get('risk_free_rate', '0.04')))
        self.min_floor_weight: Decimal = Decimal(str(self.config.get('min_floor_weight', '0.05')))
        self.enforce_performance: bool = self.config.get('enforce_performance', False)
        
        # Cache for Firestore client
        self._db: Optional[firestore.Client] = None
    
    def _get_db(self) -> firestore.Client:
        """Get or create Firestore client."""
        if self._db is None:
            self._db = firestore.client()
        return self._db
    
    def _fetch_agent_trades(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trades for a specific agent from tradeJournal.
        
        Args:
            user_id: User ID to query
            agent_id: Agent identifier (e.g., 'WhaleFlowAgent')
            limit: Maximum number of trades to fetch
            
        Returns:
            List of trade dictionaries sorted by closed_at (most recent first)
        """
        try:
            db = self._get_db()
            
            # Query: users/{uid}/tradeJournal/ where agent_id == agent_id
            # Order by closed_at descending, limit to last N trades
            trades_ref = (
                db.collection('users')
                .document(user_id)
                .collection('tradeJournal')
                .where('agent_id', '==', agent_id)
                .order_by('closed_at', direction=firestore.Query.DESCENDING)
                .limit(limit)
            )
            
            trades = []
            for doc in trades_ref.stream():
                trade_data = doc.to_dict()
                if trade_data:
                    trades.append(trade_data)
            
            logger.info(f"Fetched {len(trades)} trades for agent '{agent_id}'")
            return trades
            
        except Exception as e:
            logger.exception(f"Error fetching trades for agent '{agent_id}': {e}")
            return []
    
    def _calculate_daily_returns(self, trades: List[Dict[str, Any]]) -> List[Decimal]:
        """
        Calculate daily returns from trade history.
        
        For simplicity, we treat each trade as a "day" and calculate return as:
        return = (realized_pnl / entry_capital) * 100
        
        In production, you might group trades by actual date and aggregate.
        
        Args:
            trades: List of trade dictionaries with 'realized_pnl' and 'entry_price'/'quantity'
            
        Returns:
            List of Decimal daily returns
        """
        returns = []
        
        for trade in trades:
            try:
                # Get P&L
                pnl_str = trade.get('realized_pnl', '0')
                pnl = Decimal(str(pnl_str))
                
                # Calculate entry capital (entry_price * quantity)
                entry_price_str = trade.get('entry_price', '0')
                quantity_str = trade.get('quantity', '0')
                
                entry_price = Decimal(str(entry_price_str))
                quantity = Decimal(str(quantity_str))
                
                entry_capital = entry_price * quantity
                
                if entry_capital == Decimal('0'):
                    logger.warning(f"Trade {trade.get('trade_id')} has zero entry capital, skipping")
                    continue
                
                # Calculate return as percentage
                trade_return = (pnl / entry_capital) * Decimal('100')
                returns.append(trade_return)
                
            except (InvalidOperation, ValueError, KeyError) as e:
                logger.warning(f"Error calculating return for trade {trade.get('trade_id')}: {e}")
                continue
        
        return returns
    
    def _calculate_sharpe_ratio(
        self,
        returns: List[Decimal],
        risk_free_rate: Decimal = Decimal('0.04')
    ) -> Decimal:
        """
        Calculate Sharpe Ratio from a list of returns.
        
        Formula: Sharpe = (mean_return - risk_free_rate) / std_dev_return
        
        Note: We assume returns are already in percentage form (e.g., 2.5 for 2.5%)
        and risk_free_rate is annual (e.g., 0.04 for 4%).
        
        We convert annual risk_free_rate to daily by dividing by 252 (trading days).
        
        Args:
            returns: List of Decimal returns (in percentage)
            risk_free_rate: Annual risk-free rate (e.g., 0.04 for 4%)
            
        Returns:
            Sharpe Ratio as Decimal
        """
        if not returns:
            logger.warning("No returns provided for Sharpe calculation, returning 0")
            return Decimal('0')
        
        n = len(returns)
        
        # Calculate mean return
        mean_return = sum(returns) / Decimal(str(n))
        
        # Convert annual risk-free rate to daily (assuming 252 trading days)
        daily_risk_free = (risk_free_rate / Decimal('252')) * Decimal('100')  # Convert to percentage
        
        # Calculate excess return
        excess_return = mean_return - daily_risk_free
        
        # Calculate standard deviation
        if n < 2:
            logger.warning("Need at least 2 returns for std dev, returning 0 Sharpe")
            return Decimal('0')
        
        variance_sum = sum((r - mean_return) ** 2 for r in returns)
        variance = variance_sum / Decimal(str(n - 1))  # Sample variance
        
        # Convert to float for sqrt, then back to Decimal
        # This is acceptable since we're only using float for the sqrt operation
        try:
            variance_float = float(variance)
            if variance_float < 0:
                logger.warning(f"Negative variance detected: {variance}, returning 0 Sharpe")
                return Decimal('0')
            
            std_dev_float = math.sqrt(variance_float)
            std_dev = Decimal(str(std_dev_float))
            
        except (ValueError, OverflowError) as e:
            logger.warning(f"Error calculating std dev: {e}, returning 0 Sharpe")
            return Decimal('0')
        
        if std_dev == Decimal('0'):
            logger.warning("Standard deviation is zero, returning 0 Sharpe")
            return Decimal('0')
        
        # Calculate Sharpe Ratio
        sharpe = excess_return / std_dev
        
        return sharpe
    
    def _softmax_normalize(
        self,
        sharpe_ratios: Dict[str, Decimal]
    ) -> Dict[str, Decimal]:
        """
        Apply Softmax normalization to Sharpe Ratios to get capital allocation weights.
        
        Formula: weight_i = exp(sharpe_i) / sum(exp(sharpe_j) for all j)
        
        Handles negative Sharpe Ratios by applying min_floor_weight or setting to 0.0
        based on enforce_performance flag.
        
        Args:
            sharpe_ratios: Dictionary mapping agent_id to Sharpe Ratio
            
        Returns:
            Dictionary mapping agent_id to capital allocation weight (sum = 1.0)
        """
        if not sharpe_ratios:
            logger.warning("No Sharpe ratios provided, returning empty weights")
            return {}
        
        # Handle negative Sharpe Ratios
        adjusted_sharpes = {}
        for agent_id, sharpe in sharpe_ratios.items():
            if sharpe < Decimal('0'):
                if self.enforce_performance:
                    # Strictly enforce: negative Sharpe gets 0 weight
                    adjusted_sharpes[agent_id] = Decimal('0')
                    logger.info(f"Agent '{agent_id}' has negative Sharpe {sharpe:.4f}, assigning 0 weight")
                else:
                    # Allow recovery: assign floor weight
                    adjusted_sharpes[agent_id] = self.min_floor_weight
                    logger.info(
                        f"Agent '{agent_id}' has negative Sharpe {sharpe:.4f}, "
                        f"assigning floor weight {self.min_floor_weight}"
                    )
            else:
                adjusted_sharpes[agent_id] = sharpe
        
        # Filter out agents with 0 weight if enforcing performance
        if self.enforce_performance:
            active_agents = {k: v for k, v in adjusted_sharpes.items() if v > Decimal('0')}
            if not active_agents:
                logger.warning("All agents have negative Sharpe, cannot allocate capital")
                return {agent_id: Decimal('0') for agent_id in sharpe_ratios.keys()}
        else:
            active_agents = adjusted_sharpes
        
        # Apply Softmax using Decimal precision
        # Softmax: exp(x_i) / sum(exp(x_j))
        
        # For numerical stability, subtract max value before exp
        max_sharpe = max(active_agents.values())
        
        exp_values = {}
        for agent_id, sharpe in active_agents.items():
            # Convert to float for exp, then back to Decimal
            try:
                exponent_float = float(sharpe - max_sharpe)
                exp_value_float = math.exp(exponent_float)
                exp_values[agent_id] = Decimal(str(exp_value_float))
            except (OverflowError, ValueError) as e:
                logger.warning(f"Error calculating exp for agent '{agent_id}': {e}, using 0")
                exp_values[agent_id] = Decimal('0')
        
        # Calculate sum of exp values
        exp_sum = sum(exp_values.values())
        
        if exp_sum == Decimal('0'):
            logger.warning("Sum of exp values is zero, using equal weights")
            equal_weight = Decimal('1') / Decimal(str(len(active_agents)))
            return {agent_id: equal_weight for agent_id in active_agents.keys()}
        
        # Calculate normalized weights
        weights = {
            agent_id: exp_value / exp_sum
            for agent_id, exp_value in exp_values.items()
        }
        
        # Add back zero-weight agents if enforcing performance
        if self.enforce_performance:
            for agent_id in sharpe_ratios.keys():
                if agent_id not in weights:
                    weights[agent_id] = Decimal('0')
        
        # Verify weights sum to 1.0 (within tolerance)
        total_weight = sum(weights.values())
        if abs(total_weight - Decimal('1')) > Decimal('0.0001'):
            logger.warning(f"Weights sum to {total_weight}, renormalizing to 1.0")
            weights = {k: v / total_weight for k, v in weights.items()}
        
        return weights
    
    def calculate_agent_weights(self, user_id: str) -> Dict[str, Decimal]:
        """
        Calculate capital allocation weights for all agents based on historical performance.
        
        This is the main method that:
        1. Fetches recent trades for each agent
        2. Calculates daily returns
        3. Computes Sharpe Ratios
        4. Applies Softmax normalization
        
        Args:
            user_id: User ID to query for trade history
            
        Returns:
            Dictionary mapping agent_id to capital allocation weight (Decimal, sum = 1.0)
        """
        logger.info(f"Calculating agent weights for user '{user_id}'")
        
        sharpe_ratios: Dict[str, Decimal] = {}
        
        # Calculate Sharpe Ratio for each agent
        for agent_id in self.agent_ids:
            logger.info(f"Processing agent '{agent_id}'...")
            
            # Fetch trades
            trades = self._fetch_agent_trades(user_id, agent_id, limit=self.lookback_trades)
            
            if not trades:
                logger.warning(f"No trades found for agent '{agent_id}', assigning 0 Sharpe")
                sharpe_ratios[agent_id] = Decimal('0')
                continue
            
            # Calculate returns
            returns = self._calculate_daily_returns(trades)
            
            if not returns:
                logger.warning(f"No valid returns for agent '{agent_id}', assigning 0 Sharpe")
                sharpe_ratios[agent_id] = Decimal('0')
                continue
            
            # Calculate Sharpe Ratio
            sharpe = self._calculate_sharpe_ratio(returns, self.risk_free_rate)
            sharpe_ratios[agent_id] = sharpe
            
            logger.info(
                f"Agent '{agent_id}': "
                f"{len(returns)} returns, "
                f"mean={sum(returns)/Decimal(str(len(returns))):.4f}%, "
                f"Sharpe={sharpe:.4f}"
            )
        
        # Apply Softmax normalization to get weights
        weights = self._softmax_normalize(sharpe_ratios)
        
        # Log final weights
        logger.info("=" * 60)
        logger.info("MAESTRO ORCHESTRATOR - FINAL WEIGHTS")
        logger.info("=" * 60)
        for agent_id, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            sharpe = sharpe_ratios.get(agent_id, Decimal('0'))
            logger.info(f"{agent_id:20s}: {float(weight)*100:6.2f}% (Sharpe: {float(sharpe):7.4f})")
        logger.info("=" * 60)
        
        return weights
    
    def evaluate(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None
    ) -> TradingSignal:
        """
        Evaluate and return agent weight allocations.
        
        This method calculates the optimal capital allocation across agents
        based on their historical performance (Sharpe Ratios).
        
        The weights are stored in the metadata of the signal for use by
        downstream execution systems.
        
        Args:
            market_data: Current market data (not used directly by Maestro)
            account_snapshot: Current account state (used to extract user_id)
            regime: Optional market regime (not used directly by Maestro)
            
        Returns:
            TradingSignal with action=HOLD and weights in metadata
        """
        try:
            # Extract user_id from account snapshot
            # This assumes account_snapshot has a 'user_id' or 'uid' field
            user_id = account_snapshot.get('user_id') or account_snapshot.get('uid')
            
            if not user_id:
                logger.error("No user_id found in account_snapshot, cannot calculate weights")
                return TradingSignal(
                    signal_type=SignalType.HOLD,
                    symbol=market_data.get("symbol", "SPY"),
                    confidence=0.0,
                    reasoning="Error: No user_id provided",
                    metadata={'error': 'missing_user_id'}
                )
            
            # Calculate agent weights
            weights = self.calculate_agent_weights(user_id)
            
            if not weights:
                return TradingSignal(
                    signal_type=SignalType.HOLD,
                    symbol=market_data.get("symbol", "SPY"),
                    confidence=0.0,
                    reasoning="No agent weights calculated (no trade history available)",
                    metadata={'weights': {}}
                )
            
            # Convert Decimal weights to float for JSON serialization
            weights_float = {k: float(v) for k, v in weights.items()}
            
            # Return signal with weights in metadata
            return TradingSignal(
                signal_type=SignalType.HOLD,  # Maestro doesn't generate trades directly
                symbol=market_data.get("symbol", "SPY"),
                confidence=1.0,
                reasoning=(
                    f"Agent weights calculated based on {self.lookback_trades} recent trades per agent. "
                    f"Top performer: {max(weights.items(), key=lambda x: x[1])[0] if weights else 'N/A'}"
                ),
                metadata={
                    'weights': weights_float,
                    'agent_ids': self.agent_ids,
                    'lookback_trades': self.lookback_trades,
                    'risk_free_rate': float(self.risk_free_rate)
                }
            )
            
        except Exception as e:
            logger.exception(f"Error in MaestroOrchestrator.evaluate: {e}")
            return TradingSignal(
                signal_type=SignalType.HOLD,
                symbol=market_data.get("symbol", "SPY"),
                confidence=0.0,
                reasoning=f"Error calculating agent weights: {str(e)}",
                metadata={'error': str(e)}
            )
