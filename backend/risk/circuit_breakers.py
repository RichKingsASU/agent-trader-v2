"""
Smart Risk Circuit Breakers for BaseStrategy Execution Loop.

This module implements three circuit breakers that protect user capital:
1. Daily Loss Limit: Switch strategies to SHADOW_MODE if daily PnL drops below -2%
2. VIX Guard: Reduce allocation by 50% when VIX > 30
3. Concentration Check: Prevent buying if ticker > 20% of portfolio
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..ledger.models import LedgerTrade
from ..ledger.pnl import compute_fifo_pnl, aggregate_pnl

logger = logging.getLogger(__name__)


class CircuitBreakerType(Enum):
    """Types of circuit breakers."""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    VIX_GUARD = "vix_guard"
    CONCENTRATION_CHECK = "concentration_check"


@dataclass(frozen=True)
class CircuitBreakerEvent:
    """
    Event triggered when a circuit breaker activates.
    
    Attributes:
        breaker_type: Which circuit breaker was triggered
        timestamp: When the event occurred
        user_id: User whose trading triggered the breaker
        tenant_id: Tenant ID
        strategy_id: Strategy ID (if applicable)
        severity: Severity level (info, warning, critical)
        message: Human-readable description
        metadata: Additional context data
    """
    breaker_type: CircuitBreakerType
    timestamp: datetime
    user_id: str
    tenant_id: str
    strategy_id: Optional[str]
    severity: str
    message: str
    metadata: Dict[str, Any]


class CircuitBreakerManager:
    """
    Manages all circuit breakers for risk management.
    
    This class is designed to be called during the BaseStrategy evaluate()
    method to check for risk conditions before executing trades.
    """
    
    # Circuit breaker thresholds
    DAILY_LOSS_THRESHOLD = -0.02  # -2%
    VIX_THRESHOLD = 30.0
    CONCENTRATION_THRESHOLD = 0.20  # 20%
    ALLOCATION_REDUCTION_FACTOR = 0.5  # 50% reduction
    
    def __init__(self, db_client: Any = None, notification_service: Any = None):
        """
        Initialize the circuit breaker manager.
        
        Args:
            db_client: Firestore client for accessing trade history and VIX data
            notification_service: Service for sending notifications (optional)
        """
        self.db = db_client
        self.notification_service = notification_service
        self._vix_cache: Optional[Tuple[float, datetime]] = None
        self._cache_ttl_seconds = 300  # 5 minutes
    
    def check_daily_loss_limit(
        self,
        *,
        tenant_id: str,
        user_id: str,
        strategy_id: str,
        trades: List[LedgerTrade],
        starting_equity: float,
    ) -> Tuple[bool, Optional[CircuitBreakerEvent]]:
        """
        Check if daily PnL has dropped below -2% threshold.
        
        Args:
            tenant_id: Tenant ID
            user_id: User ID
            strategy_id: Strategy ID
            trades: List of ledger trades for today
            starting_equity: Starting equity at beginning of day
        
        Returns:
            Tuple of (should_trigger, event)
            - should_trigger: True if circuit breaker should activate
            - event: CircuitBreakerEvent if triggered, None otherwise
        """
        if not trades or starting_equity <= 0:
            return False, None
        
        try:
            # Get current day's trades only
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_trades = [t for t in trades if t.ts >= today_start]
            
            if not today_trades:
                return False, None
            
            # Compute PnL for today
            pnl_results = compute_fifo_pnl(
                trades=today_trades,
                mark_prices={},  # No unrealized needed for this check
                as_of=None,
            )
            
            aggregated = aggregate_pnl(pnl_results)
            key = (tenant_id, user_id, strategy_id)
            
            if key not in aggregated:
                return False, None
            
            realized_pnl = aggregated[key].get("realized_pnl", 0.0)
            pnl_percentage = realized_pnl / starting_equity
            
            logger.info(
                f"Daily Loss Check: user={user_id}, strategy={strategy_id}, "
                f"PnL=${realized_pnl:.2f}, percentage={pnl_percentage*100:.2f}%, "
                f"threshold={self.DAILY_LOSS_THRESHOLD*100:.2f}%"
            )
            
            if pnl_percentage <= self.DAILY_LOSS_THRESHOLD:
                event = CircuitBreakerEvent(
                    breaker_type=CircuitBreakerType.DAILY_LOSS_LIMIT,
                    timestamp=datetime.now(timezone.utc),
                    user_id=user_id,
                    tenant_id=tenant_id,
                    strategy_id=strategy_id,
                    severity="critical",
                    message=(
                        f"Daily loss limit breached: {pnl_percentage*100:.2f}% "
                        f"(${realized_pnl:.2f}). Switching to SHADOW_MODE."
                    ),
                    metadata={
                        "realized_pnl": realized_pnl,
                        "pnl_percentage": pnl_percentage,
                        "starting_equity": starting_equity,
                        "threshold": self.DAILY_LOSS_THRESHOLD,
                    }
                )
                logger.warning(f"🚨 CIRCUIT BREAKER TRIGGERED: {event.message}")
                return True, event
            
            return False, None
            
        except Exception as e:
            logger.error(f"Error checking daily loss limit: {e}", exc_info=True)
            return False, None
    
    def check_vix_guard(
        self,
        *,
        allocation: float,
    ) -> Tuple[float, Optional[CircuitBreakerEvent]]:
        """
        Check VIX and reduce allocation if > 30.
        
        Args:
            allocation: Original allocation amount
        
        Returns:
            Tuple of (adjusted_allocation, event)
            - adjusted_allocation: Potentially reduced allocation
            - event: CircuitBreakerEvent if triggered, None otherwise
        """
        try:
            vix_value = self._get_current_vix()
            
            if vix_value is None:
                logger.warning("VIX data not available, skipping VIX guard")
                return allocation, None
            
            logger.info(f"VIX Guard Check: VIX={vix_value:.2f}, threshold={self.VIX_THRESHOLD}")
            
            if vix_value > self.VIX_THRESHOLD:
                adjusted_allocation = allocation * self.ALLOCATION_REDUCTION_FACTOR
                
                event = CircuitBreakerEvent(
                    breaker_type=CircuitBreakerType.VIX_GUARD,
                    timestamp=datetime.now(timezone.utc),
                    user_id="",  # Set by caller
                    tenant_id="",  # Set by caller
                    strategy_id=None,
                    severity="warning",
                    message=(
                        f"VIX elevated at {vix_value:.2f} (threshold: {self.VIX_THRESHOLD}). "
                        f"Reducing allocation from ${allocation:.2f} to ${adjusted_allocation:.2f} "
                        f"({self.ALLOCATION_REDUCTION_FACTOR*100:.0f}% of original)."
                    ),
                    metadata={
                        "vix_value": vix_value,
                        "threshold": self.VIX_THRESHOLD,
                        "original_allocation": allocation,
                        "adjusted_allocation": adjusted_allocation,
                        "reduction_factor": self.ALLOCATION_REDUCTION_FACTOR,
                    }
                )
                logger.warning(f"⚠️  VIX GUARD ACTIVATED: {event.message}")
                return adjusted_allocation, event
            
            return allocation, None
            
        except Exception as e:
            logger.error(f"Error checking VIX guard: {e}", exc_info=True)
            return allocation, None
    
    def check_concentration(
        self,
        *,
        ticker: str,
        signal_action: str,
        positions: Dict[str, Any],
        total_portfolio_value: float,
    ) -> Tuple[str, Optional[CircuitBreakerEvent]]:
        """
        Check if ticker concentration exceeds 20% of portfolio.
        
        Before executing a BUY signal, this checks if the ticker already
        represents more than 20% of the total portfolio value. If so,
        the signal is downgraded to HOLD.
        
        Args:
            ticker: Symbol being traded
            signal_action: Original signal action (BUY, SELL, HOLD)
            positions: Dictionary of current positions {symbol: position_data}
            total_portfolio_value: Total portfolio value in USD
        
        Returns:
            Tuple of (adjusted_action, event)
            - adjusted_action: Potentially downgraded action
            - event: CircuitBreakerEvent if triggered, None otherwise
        """
        # Only check on BUY signals
        if signal_action != "BUY":
            return signal_action, None
        
        if total_portfolio_value <= 0:
            logger.warning("Total portfolio value is 0 or negative, skipping concentration check")
            return signal_action, None
        
        try:
            # Calculate current ticker value in portfolio
            ticker_value = 0.0
            if ticker in positions:
                position = positions[ticker]
                qty = float(position.get("qty", 0))
                current_price = float(position.get("current_price", 0))
                ticker_value = qty * current_price
            
            concentration = ticker_value / total_portfolio_value if total_portfolio_value > 0 else 0.0
            
            logger.info(
                f"Concentration Check: ticker={ticker}, value=${ticker_value:.2f}, "
                f"portfolio=${total_portfolio_value:.2f}, concentration={concentration*100:.2f}%, "
                f"threshold={self.CONCENTRATION_THRESHOLD*100:.0f}%"
            )
            
            if concentration > self.CONCENTRATION_THRESHOLD:
                event = CircuitBreakerEvent(
                    breaker_type=CircuitBreakerType.CONCENTRATION_CHECK,
                    timestamp=datetime.now(timezone.utc),
                    user_id="",  # Set by caller
                    tenant_id="",  # Set by caller
                    strategy_id=None,
                    severity="warning",
                    message=(
                        f"Concentration limit exceeded for {ticker}: {concentration*100:.2f}% "
                        f"(threshold: {self.CONCENTRATION_THRESHOLD*100:.0f}%). "
                        f"Downgrading BUY to HOLD."
                    ),
                    metadata={
                        "ticker": ticker,
                        "ticker_value": ticker_value,
                        "portfolio_value": total_portfolio_value,
                        "concentration": concentration,
                        "threshold": self.CONCENTRATION_THRESHOLD,
                        "original_action": signal_action,
                        "adjusted_action": "HOLD",
                    }
                )
                logger.warning(f"⚠️  CONCENTRATION GUARD ACTIVATED: {event.message}")
                return "HOLD", event
            
            return signal_action, None
            
        except Exception as e:
            logger.error(f"Error checking concentration: {e}", exc_info=True)
            return signal_action, None
    
    def _get_current_vix(self) -> Optional[float]:
        """
        Get current VIX value from cache or Firestore.
        
        Returns:
            Current VIX value or None if unavailable
        """
        # Check cache first
        if self._vix_cache is not None:
            vix_value, cached_at = self._vix_cache
            age_seconds = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age_seconds < self._cache_ttl_seconds:
                return vix_value
        
        # Fetch from Firestore
        if self.db is None:
            logger.warning("No database client available for VIX lookup")
            return None
        
        try:
            # Firestore path: systemStatus/vix_data
            doc_ref = self.db.collection("systemStatus").document("vix_data")
            doc = doc_ref.get()
            
            if not doc.exists:
                logger.warning("VIX data not found in Firestore")
                return None
            
            data = doc.to_dict() or {}
            vix_value = data.get("current_value")
            
            if vix_value is None:
                logger.warning("VIX value is None in Firestore document")
                return None
            
            # Update cache
            self._vix_cache = (float(vix_value), datetime.now(timezone.utc))
            logger.info(f"Fetched VIX from Firestore: {vix_value}")
            return float(vix_value)
            
        except Exception as e:
            logger.error(f"Error fetching VIX from Firestore: {e}", exc_info=True)
            return None
    
    async def handle_circuit_breaker_event(
        self,
        event: CircuitBreakerEvent,
    ) -> None:
        """
        Handle a circuit breaker event by logging and optionally notifying.
        
        Args:
            event: The circuit breaker event to handle
        """
        # Log the event
        logger.warning(
            f"Circuit Breaker Event: type={event.breaker_type.value}, "
            f"severity={event.severity}, user={event.user_id}, "
            f"message={event.message}"
        )
        
        # Store event in Firestore for audit trail
        if self.db is not None:
            try:
                event_doc = {
                    "breaker_type": event.breaker_type.value,
                    "timestamp": event.timestamp,
                    "user_id": event.user_id,
                    "tenant_id": event.tenant_id,
                    "strategy_id": event.strategy_id,
                    "severity": event.severity,
                    "message": event.message,
                    "metadata": event.metadata,
                }
                
                # Store in user's events collection
                self.db.collection("users").document(event.user_id).collection(
                    "circuit_breaker_events"
                ).add(event_doc)
                
                logger.info(f"Stored circuit breaker event in Firestore for user {event.user_id}")
                
            except Exception as e:
                logger.error(f"Error storing circuit breaker event: {e}", exc_info=True)
        
        # Send notification if service available
        if self.notification_service is not None:
            try:
                await self.notification_service.send_notification(
                    user_id=event.user_id,
                    title=f"Circuit Breaker: {event.breaker_type.value}",
                    message=event.message,
                    severity=event.severity,
                )
            except Exception as e:
                logger.error(f"Error sending notification: {e}", exc_info=True)
    
    async def switch_strategies_to_shadow_mode(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> None:
        """
        Switch all active strategies for a user to SHADOW_MODE.
        
        This is called when the daily loss limit is breached.
        
        Args:
            tenant_id: Tenant ID
            user_id: User ID
        """
        if self.db is None:
            logger.error("Cannot switch to shadow mode: no database client")
            return
        
        try:
            # Query all active strategies for this user
            strategies_ref = (
                self.db.collection("tenants")
                .document(tenant_id)
                .collection("users")
                .document(user_id)
                .collection("strategies")
            )
            
            strategies = strategies_ref.where("status", "==", "active").stream()
            
            count = 0
            for strategy_doc in strategies:
                strategy_ref = strategies_ref.document(strategy_doc.id)
                strategy_ref.update({
                    "execution_mode": "SHADOW_MODE",
                    "shadow_mode_reason": "daily_loss_limit_breached",
                    "shadow_mode_activated_at": datetime.now(timezone.utc),
                })
                count += 1
                logger.info(f"Switched strategy {strategy_doc.id} to SHADOW_MODE")
            
            logger.warning(
                f"Switched {count} strategies to SHADOW_MODE for user {user_id} "
                f"due to daily loss limit breach"
            )
            
        except Exception as e:
            logger.error(f"Error switching strategies to shadow mode: {e}", exc_info=True)
