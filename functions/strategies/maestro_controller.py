"""
Maestro Orchestration Controller

The Maestro sits above the StrategyLoader and manages:
1. Dynamic capital allocation based on Sharpe Ratios
2. Systemic risk detection and override
3. Just-In-Time (JIT) Identity for agent tracking
4. Auditability and AI-powered decision summaries

This implements 2026 institutional standards for multi-agent coordination.
"""

import asyncio
import logging
import math
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from google.cloud import firestore

logger = logging.getLogger(__name__)


class AgentMode(Enum):
    """Operating mode for a trading agent/strategy."""
    ACTIVE = "ACTIVE"
    REDUCED = "REDUCED"  # Allocation reduced due to performance
    SHADOW = "SHADOW_MODE"  # Paper trading only, no real execution
    DISABLED = "DISABLED"


@dataclass
class AgentIdentity:
    """
    Just-In-Time Identity for agent tracking.
    
    Prevents "Double Spend" and "Agent Sprawl" by ensuring every signal
    includes unique identification and a nonce.
    """
    agent_id: str
    strategy_name: str
    nonce: str
    timestamp: datetime
    session_id: str  # Unique per invocation
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "strategy_name": self.strategy_name,
            "nonce": self.nonce,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id
        }


@dataclass
class StrategyPerformanceMetrics:
    """Performance metrics for a strategy."""
    strategy_name: str
    sharpe_ratio: float
    annualized_return: float
    daily_returns: List[float]
    total_return: float
    max_drawdown: float
    volatility: float
    win_rate: float
    data_points: int
    last_updated: datetime
    
    def is_healthy(self) -> bool:
        """Check if strategy meets minimum health thresholds."""
        return (
            self.sharpe_ratio >= 0.5 and
            self.data_points >= 5 and  # Need at least 5 days of data
            self.max_drawdown > -0.5  # Max 50% drawdown
        )


@dataclass
class AllocationDecision:
    """Capital allocation decision by the Maestro."""
    strategy_name: str
    original_allocation: float
    final_allocation: float
    mode: AgentMode
    reasoning: str
    sharpe_ratio: float
    timestamp: datetime


@dataclass
class MaestroDecision:
    """
    A complete Maestro orchestration decision.
    
    Includes all allocation adjustments, systemic risk overrides,
    and AI-generated summaries.
    """
    timestamp: datetime
    session_id: str
    allocation_decisions: List[AllocationDecision] = field(default_factory=list)
    systemic_risk_detected: bool = False
    systemic_risk_details: Optional[str] = None
    signals_modified: Dict[str, str] = field(default_factory=dict)  # strategy -> reason
    ai_summary: Optional[str] = None
    
    def to_firestore_doc(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible document."""
        return {
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "allocation_decisions": [
                {
                    "strategy_name": d.strategy_name,
                    "original_allocation": d.original_allocation,
                    "final_allocation": d.final_allocation,
                    "mode": d.mode.value,
                    "reasoning": d.reasoning,
                    "sharpe_ratio": d.sharpe_ratio,
                    "timestamp": d.timestamp.isoformat()
                }
                for d in self.allocation_decisions
            ],
            "systemic_risk_detected": self.systemic_risk_detected,
            "systemic_risk_details": self.systemic_risk_details,
            "signals_modified": self.signals_modified,
            "ai_summary": self.ai_summary
        }


class MaestroController:
    """
    The Maestro Orchestration Layer.
    
    Sits above the StrategyLoader to manage agent sprawl, dynamic capital
    allocation, systemic risk detection, and auditability.
    
    Architecture:
    - Multi-Agent: Coordinates multiple strategies with weighted signals
    - Environment Aware: Integrates with GEX, VIX, and market regime data
    - Security: JIT Identity and nonces prevent double-spend
    - Risk: Real-time Sharpe-based throttling and allocation adjustment
    - Outcome: Automated journaling with AI summaries
    """
    
    # Sharpe Ratio thresholds for allocation adjustments
    SHARPE_THRESHOLD_REDUCE = 1.0  # Reduce allocation by 50%
    SHARPE_THRESHOLD_SHADOW = 0.5  # Move to shadow mode
    
    # Systemic risk detection
    SYSTEMIC_SELL_THRESHOLD = 3  # If 3+ agents signal SELL, override all BUYs
    
    # Performance lookback
    PERFORMANCE_LOOKBACK_DAYS = 30
    MIN_DATA_POINTS = 5  # Minimum daily returns needed for Sharpe calculation
    
    def __init__(
        self,
        db: firestore.Client,
        tenant_id: str = "default",
        uid: Optional[str] = None
    ):
        """
        Initialize the Maestro Controller.
        
        Args:
            db: Firestore client
            tenant_id: Tenant identifier for multi-tenancy
            uid: User identifier (optional, for user-specific performance)
        """
        self.db = db
        self.tenant_id = tenant_id
        self.uid = uid
        self.session_id = self._generate_session_id()
        
        # Cache for strategy performance metrics
        self._performance_cache: Dict[str, StrategyPerformanceMetrics] = {}
        self._cache_expiry = datetime.now(timezone.utc)
        self._cache_ttl = timedelta(minutes=5)
        
        logger.info(
            f"MaestroController initialized: tenant={tenant_id}, uid={uid}, "
            f"session={self.session_id}"
        )
    
    def _generate_session_id(self) -> str:
        """Generate a unique session identifier."""
        timestamp = int(time.time() * 1000)
        random_suffix = secrets.token_hex(8)
        return f"maestro_{timestamp}_{random_suffix}"
    
    def generate_agent_identity(self, strategy_name: str) -> AgentIdentity:
        """
        Generate Just-In-Time Identity for a strategy/agent.
        
        Args:
            strategy_name: Name of the strategy
            
        Returns:
            AgentIdentity with unique nonce and tracking info
        """
        agent_id = f"{self.tenant_id}_{strategy_name}"
        nonce = secrets.token_hex(16)  # 32-character hex nonce
        
        return AgentIdentity(
            agent_id=agent_id,
            strategy_name=strategy_name,
            nonce=nonce,
            timestamp=datetime.now(timezone.utc),
            session_id=self.session_id
        )
    
    async def fetch_strategy_performance(
        self,
        strategy_name: str,
        lookback_days: int = PERFORMANCE_LOOKBACK_DAYS
    ) -> Optional[StrategyPerformanceMetrics]:
        """
        Fetch historical performance for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            lookback_days: Number of days to look back
            
        Returns:
            StrategyPerformanceMetrics or None if insufficient data
        """
        # Check cache first
        now = datetime.now(timezone.utc)
        if (strategy_name in self._performance_cache and 
            now < self._cache_expiry):
            return self._performance_cache[strategy_name]
        
        try:
            # Query Firestore for daily P&L data
            # Path: tenants/{tenant_id}/strategy_performance/{perf_id}
            cutoff_date = now - timedelta(days=lookback_days)
            
            # Build query for strategy performance snapshots
            paths_base = f"tenants/{self.tenant_id}/strategy_performance"
            query = self.db.collection(paths_base)
            query = query.where("strategy_id", "==", strategy_name)
            query = query.where("period_start", ">=", cutoff_date)
            query = query.order_by("period_start", direction=firestore.Query.DESCENDING)
            query = query.limit(lookback_days)
            
            docs = list(query.stream())
            
            if len(docs) < self.MIN_DATA_POINTS:
                logger.warning(
                    f"Insufficient data for {strategy_name}: "
                    f"{len(docs)} data points (need {self.MIN_DATA_POINTS})"
                )
                return None
            
            # Extract daily returns
            daily_pnls = []
            total_pnl = 0.0
            
            for doc in docs:
                data = doc.to_dict()
                realized_pnl = float(data.get("realized_pnl", 0.0))
                unrealized_pnl = float(data.get("unrealized_pnl", 0.0))
                total_daily_pnl = realized_pnl + unrealized_pnl
                daily_pnls.append(total_daily_pnl)
                total_pnl += realized_pnl
            
            # Calculate daily returns (assuming some base capital)
            # For Sharpe, we need returns not absolute P&L
            # Use a simple percentage return calculation
            if not daily_pnls:
                return None
            
            # Calculate metrics
            metrics = self._calculate_performance_metrics(
                strategy_name=strategy_name,
                daily_pnls=daily_pnls,
                lookback_days=len(docs)
            )
            
            # Cache the result
            self._performance_cache[strategy_name] = metrics
            self._cache_expiry = now + self._cache_ttl
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error fetching performance for {strategy_name}: {e}", exc_info=True)
            return None
    
    def _calculate_performance_metrics(
        self,
        strategy_name: str,
        daily_pnls: List[float],
        lookback_days: int
    ) -> StrategyPerformanceMetrics:
        """
        Calculate performance metrics from daily P&L data.
        
        Args:
            strategy_name: Name of the strategy
            daily_pnls: List of daily P&L values
            lookback_days: Number of days in the lookback period
            
        Returns:
            StrategyPerformanceMetrics
        """
        if not daily_pnls or len(daily_pnls) < 2:
            # Return default metrics for insufficient data
            return StrategyPerformanceMetrics(
                strategy_name=strategy_name,
                sharpe_ratio=0.0,
                annualized_return=0.0,
                daily_returns=[],
                total_return=0.0,
                max_drawdown=0.0,
                volatility=0.0,
                win_rate=0.0,
                data_points=len(daily_pnls),
                last_updated=datetime.now(timezone.utc)
            )
        
        # Convert P&L to percentage returns (assume base capital of $10,000)
        BASE_CAPITAL = 10000.0
        daily_returns = [pnl / BASE_CAPITAL for pnl in daily_pnls]
        
        # Calculate mean and std dev of returns
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_return) ** 2 for r in daily_returns) / len(daily_returns)
        std_dev = math.sqrt(variance)
        
        # Calculate Sharpe Ratio
        # Formula: S = sqrt(252) * (mean(daily_returns) / std(daily_returns))
        # Assuming 252 trading days per year
        RISK_FREE_RATE = 0.04  # 4% annual
        daily_rf_rate = RISK_FREE_RATE / 252
        
        if std_dev > 0:
            sharpe_ratio = ((mean_return - daily_rf_rate) / std_dev) * math.sqrt(252)
        else:
            sharpe_ratio = 0.0
        
        # Calculate total return
        total_return = sum(daily_returns)
        
        # Calculate annualized return
        if lookback_days > 0:
            years = lookback_days / 252.0
            annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
        else:
            annualized_return = 0.0
        
        # Calculate maximum drawdown
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        
        for ret in daily_returns:
            cumulative += ret
            if cumulative > peak:
                peak = cumulative
            drawdown = (cumulative - peak) / (1 + peak) if peak > 0 else 0.0
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        
        # Calculate win rate
        winning_days = sum(1 for r in daily_returns if r > 0)
        win_rate = winning_days / len(daily_returns) if daily_returns else 0.0
        
        # Calculate annualized volatility
        volatility = std_dev * math.sqrt(252)
        
        return StrategyPerformanceMetrics(
            strategy_name=strategy_name,
            sharpe_ratio=sharpe_ratio,
            annualized_return=annualized_return,
            daily_returns=daily_returns,
            total_return=total_return,
            max_drawdown=max_drawdown,
            volatility=volatility,
            win_rate=win_rate,
            data_points=len(daily_pnls),
            last_updated=datetime.now(timezone.utc)
        )
    
    async def calculate_strategy_weights(
        self,
        strategies: Dict[str, Any]
    ) -> Dict[str, Tuple[float, AgentMode]]:
        """
        Calculate allocation weights for each strategy based on Sharpe Ratios.
        
        Implementation of the Maestro Pattern:
        - Sharpe < 0.5: SHADOW_MODE (paper trading only)
        - Sharpe < 1.0: Reduce allocation by 50%
        - Sharpe >= 1.0: Full allocation
        
        Args:
            strategies: Dictionary of strategy name -> strategy instance
            
        Returns:
            Dictionary of strategy name -> (weight_multiplier, mode)
            where weight_multiplier is in [0.0, 1.0]
        """
        weights: Dict[str, Tuple[float, AgentMode]] = {}
        allocation_decisions: List[AllocationDecision] = []
        
        logger.info(f"Calculating strategy weights for {len(strategies)} strategies...")
        
        for strategy_name in strategies.keys():
            # Fetch performance metrics
            metrics = await self.fetch_strategy_performance(strategy_name)
            
            if metrics is None or not metrics.is_healthy():
                # Insufficient or unhealthy data - use default allocation
                logger.info(
                    f"Strategy {strategy_name}: Insufficient/unhealthy data, "
                    f"using default allocation"
                )
                weights[strategy_name] = (1.0, AgentMode.ACTIVE)
                
                allocation_decisions.append(AllocationDecision(
                    strategy_name=strategy_name,
                    original_allocation=1.0,
                    final_allocation=1.0,
                    mode=AgentMode.ACTIVE,
                    reasoning="Insufficient historical data for Sharpe-based adjustment",
                    sharpe_ratio=0.0,
                    timestamp=datetime.now(timezone.utc)
                ))
                continue
            
            # Apply Maestro allocation logic based on Sharpe Ratio
            sharpe = metrics.sharpe_ratio
            original_weight = 1.0
            
            if sharpe < self.SHARPE_THRESHOLD_SHADOW:
                # Move to shadow mode (paper trading)
                weight = 0.0
                mode = AgentMode.SHADOW
                reasoning = (
                    f"Sharpe Ratio {sharpe:.2f} < {self.SHARPE_THRESHOLD_SHADOW}. "
                    f"Moving to SHADOW_MODE for re-training."
                )
            elif sharpe < self.SHARPE_THRESHOLD_REDUCE:
                # Reduce allocation by 50%
                weight = 0.5
                mode = AgentMode.REDUCED
                reasoning = (
                    f"Sharpe Ratio {sharpe:.2f} < {self.SHARPE_THRESHOLD_REDUCE}. "
                    f"Reducing allocation by 50%."
                )
            else:
                # Full allocation
                weight = 1.0
                mode = AgentMode.ACTIVE
                reasoning = (
                    f"Sharpe Ratio {sharpe:.2f} >= {self.SHARPE_THRESHOLD_REDUCE}. "
                    f"Full allocation maintained."
                )
            
            weights[strategy_name] = (weight, mode)
            
            allocation_decisions.append(AllocationDecision(
                strategy_name=strategy_name,
                original_allocation=original_weight,
                final_allocation=weight,
                mode=mode,
                reasoning=reasoning,
                sharpe_ratio=sharpe,
                timestamp=datetime.now(timezone.utc)
            ))
            
            logger.info(
                f"Strategy {strategy_name}: Sharpe={sharpe:.3f}, "
                f"Weight={weight:.2f}, Mode={mode.value}"
            )
        
        # Store allocation decisions (will be part of MaestroDecision)
        self._last_allocation_decisions = allocation_decisions
        
        return weights
    
    def apply_systemic_risk_override(
        self,
        signals: Dict[str, Dict[str, Any]]
    ) -> Tuple[Dict[str, Dict[str, Any]], bool, Optional[str]]:
        """
        Apply systemic risk override to signals.
        
        Maestro Override Logic:
        If more than 3 agents return 'SELL' signals simultaneously,
        override all 'BUY' signals to preserve liquidity.
        
        Args:
            signals: Dictionary of strategy name -> signal
            
        Returns:
            Tuple of (modified_signals, systemic_risk_detected, details)
        """
        # Count SELL signals
        sell_count = sum(
            1 for signal in signals.values()
            if isinstance(signal, dict) and signal.get("action") == "SELL"
        )
        
        if sell_count >= self.SYSTEMIC_SELL_THRESHOLD:
            # SYSTEMIC RISK DETECTED - Override all BUY signals
            logger.warning(
                f"🚨 SYSTEMIC RISK DETECTED: {sell_count} agents signaling SELL. "
                f"Overriding all BUY signals to preserve liquidity."
            )
            
            modified_signals = {}
            signals_modified = {}
            
            for strategy_name, signal in signals.items():
                if not isinstance(signal, dict):
                    modified_signals[strategy_name] = signal
                    continue
                
                if signal.get("action") == "BUY":
                    # Override BUY -> HOLD
                    modified_signals[strategy_name] = {
                        **signal,
                        "action": "HOLD",
                        "original_action": "BUY",
                        "override_reason": (
                            f"Maestro systemic risk override: "
                            f"{sell_count} strategies signaling SELL"
                        ),
                        "confidence": 0.0  # Zero out confidence on override
                    }
                    signals_modified[strategy_name] = "BUY->HOLD (systemic risk)"
                else:
                    modified_signals[strategy_name] = signal
            
            details = (
                f"Systemic risk threshold breached: {sell_count} SELL signals "
                f"(threshold: {self.SYSTEMIC_SELL_THRESHOLD}). "
                f"Overrode {len(signals_modified)} BUY signals to HOLD."
            )
            
            return modified_signals, True, details
        
        # No systemic risk detected
        return signals, False, None
    
    def enrich_signals_with_identity(
        self,
        signals: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Enrich signals with JIT Identity information.
        
        Adds agent_id and nonce to every signal to prevent double-spend
        and enable complete auditability.
        
        Args:
            signals: Dictionary of strategy name -> signal
            
        Returns:
            Enriched signals with identity information
        """
        enriched_signals = {}
        
        for strategy_name, signal in signals.items():
            if not isinstance(signal, dict):
                enriched_signals[strategy_name] = signal
                continue
            
            # Generate JIT Identity
            identity = self.generate_agent_identity(strategy_name)
            
            # Enrich signal with identity
            enriched_signals[strategy_name] = {
                **signal,
                "agent_id": identity.agent_id,
                "nonce": identity.nonce,
                "session_id": identity.session_id,
                "identity_timestamp": identity.timestamp.isoformat()
            }
        
        return enriched_signals
    
    async def generate_ai_summary(
        self,
        decision: MaestroDecision
    ) -> str:
        """
        Generate AI-powered summary of Maestro decision using Gemini.
        
        Args:
            decision: The MaestroDecision to summarize
            
        Returns:
            Human-readable AI summary
        """
        try:
            # Try to import Vertex AI
            import vertexai
            from vertexai.generative_models import GenerativeModel
            
            # Build prompt for Gemini
            prompt_parts = [
                "You are the Maestro, an AI orchestrator for a multi-agent trading system.",
                "Generate a concise, professional summary of this orchestration decision:",
                "",
                f"Session: {decision.session_id}",
                f"Timestamp: {decision.timestamp.isoformat()}",
                "",
                "Allocation Decisions:"
            ]
            
            for alloc in decision.allocation_decisions:
                prompt_parts.append(
                    f"  - {alloc.strategy_name}: {alloc.mode.value} "
                    f"(Sharpe: {alloc.sharpe_ratio:.2f}, "
                    f"Allocation: {alloc.original_allocation:.0%} → {alloc.final_allocation:.0%})"
                )
                prompt_parts.append(f"    Reasoning: {alloc.reasoning}")
            
            if decision.systemic_risk_detected:
                prompt_parts.append("")
                prompt_parts.append("⚠️ SYSTEMIC RISK OVERRIDE:")
                prompt_parts.append(f"  {decision.systemic_risk_details}")
            
            if decision.signals_modified:
                prompt_parts.append("")
                prompt_parts.append("Modified Signals:")
                for strategy, reason in decision.signals_modified.items():
                    prompt_parts.append(f"  - {strategy}: {reason}")
            
            prompt_parts.append("")
            prompt_parts.append(
                "Provide a 2-3 sentence executive summary highlighting key actions "
                "and any risk management interventions."
            )
            
            prompt = "\n".join(prompt_parts)
            
            # Generate summary using Gemini
            model = GenerativeModel("gemini-2.0-flash-exp")
            response = model.generate_content(prompt)
            
            summary = response.text.strip()
            logger.info(f"Generated AI summary: {summary}")
            
            return summary
            
        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            # Return a simple text summary as fallback
            return self._generate_text_summary(decision)
    
    def _generate_text_summary(self, decision: MaestroDecision) -> str:
        """Generate a simple text summary without AI."""
        parts = []
        
        # Count strategies by mode
        mode_counts = {}
        for alloc in decision.allocation_decisions:
            mode_counts[alloc.mode] = mode_counts.get(alloc.mode, 0) + 1
        
        parts.append(f"Maestro orchestration summary for session {decision.session_id}:")
        parts.append(
            f"Managed {len(decision.allocation_decisions)} strategies: "
            + ", ".join(f"{count} {mode.value}" for mode, count in mode_counts.items())
        )
        
        if decision.systemic_risk_detected:
            parts.append(
                f"⚠️ Systemic risk detected and mitigated: {decision.systemic_risk_details}"
            )
        
        return " ".join(parts)
    
    async def orchestrate(
        self,
        signals: Dict[str, Dict[str, Any]],
        strategies: Dict[str, Any]
    ) -> Tuple[Dict[str, Dict[str, Any]], MaestroDecision]:
        """
        Main orchestration method - the Maestro's control center.
        
        Coordinates all Maestro responsibilities:
        1. Calculate Sharpe-based weights
        2. Apply systemic risk overrides
        3. Enrich signals with JIT identity
        4. Generate AI summary
        5. Log decisions to Firestore
        
        Args:
            signals: Raw signals from strategies
            strategies: Dictionary of strategy instances
            
        Returns:
            Tuple of (orchestrated_signals, maestro_decision)
        """
        logger.info("🎭 Maestro orchestration starting...")
        start_time = datetime.now(timezone.utc)
        
        # Step 1: Calculate strategy weights based on Sharpe Ratios
        weights = await self.calculate_strategy_weights(strategies)
        
        # Step 2: Apply weights to signals (reduce allocation)
        weighted_signals = {}
        for strategy_name, signal in signals.items():
            if not isinstance(signal, dict):
                weighted_signals[strategy_name] = signal
                continue
            
            weight, mode = weights.get(strategy_name, (1.0, AgentMode.ACTIVE))
            
            # If in shadow mode, mark signal as shadow
            if mode == AgentMode.SHADOW:
                weighted_signals[strategy_name] = {
                    **signal,
                    "shadow_mode": True,
                    "allocation": 0.0,
                    "mode": mode.value
                }
            else:
                # Apply weight to allocation
                original_allocation = signal.get("allocation", 0.5)
                weighted_allocation = original_allocation * weight
                
                weighted_signals[strategy_name] = {
                    **signal,
                    "allocation": weighted_allocation,
                    "original_allocation": original_allocation,
                    "weight_multiplier": weight,
                    "mode": mode.value
                }
        
        # Step 3: Apply systemic risk override
        final_signals, risk_detected, risk_details = self.apply_systemic_risk_override(
            weighted_signals
        )
        
        signals_modified = {}
        if risk_detected:
            for strategy_name in final_signals.keys():
                if (isinstance(final_signals[strategy_name], dict) and 
                    "override_reason" in final_signals[strategy_name]):
                    signals_modified[strategy_name] = final_signals[strategy_name]["override_reason"]
        
        # Step 4: Enrich with JIT Identity
        final_signals = self.enrich_signals_with_identity(final_signals)
        
        # Step 5: Build MaestroDecision
        decision = MaestroDecision(
            timestamp=start_time,
            session_id=self.session_id,
            allocation_decisions=getattr(self, '_last_allocation_decisions', []),
            systemic_risk_detected=risk_detected,
            systemic_risk_details=risk_details,
            signals_modified=signals_modified
        )
        
        # Step 6: Generate AI summary
        decision.ai_summary = await self.generate_ai_summary(decision)
        
        # Step 7: Log to Firestore
        await self._log_decision(decision)
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"🎭 Maestro orchestration complete in {duration:.2f}s. "
            f"Systemic risk: {risk_detected}"
        )
        
        return final_signals, decision
    
    async def _log_decision(self, decision: MaestroDecision) -> None:
        """
        Log Maestro decision to Firestore for auditability.
        
        Path: systemStatus/orchestration_logs/{timestamp}_{session_id}
        """
        try:
            doc_id = f"{int(decision.timestamp.timestamp())}_{decision.session_id}"
            doc_ref = self.db.collection("systemStatus").document("orchestration_logs").collection("logs").document(doc_id)
            
            doc_data = decision.to_firestore_doc()
            doc_ref.set(doc_data)
            
            logger.info(f"Maestro decision logged to Firestore: {doc_id}")
            
        except Exception as e:
            logger.error(f"Failed to log Maestro decision: {e}", exc_info=True)
