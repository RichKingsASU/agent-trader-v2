"""
Integration of Circuit Breakers with BaseStrategy Evaluation Loop.

This module provides wrapper functions and decorators to integrate circuit breakers
into the strategy evaluation flow without modifying individual strategy implementations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from .circuit_breakers import CircuitBreakerManager, CircuitBreakerEvent
from .notifications import NotificationService

logger = logging.getLogger(__name__)


class StrategyCircuitBreakerWrapper:
    """
    Wrapper that applies circuit breakers to strategy signals.
    
    This class wraps the strategy evaluation logic and applies all
    circuit breakers before returning the final signal.
    """
    
    def __init__(
        self,
        circuit_breaker_manager: CircuitBreakerManager,
        notification_service: NotificationService,
    ):
        """
        Initialize the wrapper.
        
        Args:
            circuit_breaker_manager: Circuit breaker manager instance
            notification_service: Notification service instance
        """
        self.cb_manager = circuit_breaker_manager
        self.notification_service = notification_service
    
    async def evaluate_with_circuit_breakers(
        self,
        *,
        tenant_id: str,
        user_id: str,
        strategy_id: str,
        signal: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        trades_today: List[Any],
        starting_equity: float,
        session_start_utc: Optional[datetime] = None,
        session_end_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a trading signal with circuit breaker protections.
        
        This method applies all three circuit breakers in order:
        1. Daily Loss Limit (most critical)
        2. VIX Guard (market-wide risk)
        3. Concentration Check (position-specific risk)
        
        Args:
            tenant_id: Tenant ID
            user_id: User ID
            strategy_id: Strategy ID
            signal: Original trading signal from strategy
            account_snapshot: Current account state
            trades_today: List of trades executed today
            starting_equity: Starting equity at beginning of day
        
        Returns:
            Modified signal with circuit breaker adjustments applied
        """
        # Make a copy to avoid mutating the original
        adjusted_signal = signal.copy()
        
        # Extract signal components
        action = adjusted_signal.get("action", "HOLD")
        confidence = adjusted_signal.get("confidence", 0.0)
        reasoning = adjusted_signal.get("reasoning", "")
        allocation = adjusted_signal.get("allocation", 0.0)
        ticker = adjusted_signal.get("ticker", adjusted_signal.get("symbol", ""))
        
        circuit_breaker_triggered = False
        circuit_breaker_messages = []
        
        # 1. Check Daily Loss Limit (CRITICAL - stops all trading)
        should_trigger, loss_event = self.cb_manager.check_daily_loss_limit(
            tenant_id=tenant_id,
            user_id=user_id,
            strategy_id=strategy_id,
            trades=trades_today,
            starting_equity=starting_equity,
            session_start_utc=session_start_utc,
            session_end_utc=session_end_utc,
        )
        
        if should_trigger and loss_event:
            logger.critical(
                f"🚨 DAILY LOSS LIMIT BREACHED for user {user_id}! "
                f"Switching all strategies to SHADOW_MODE"
            )
            
            # Switch all strategies to shadow mode
            await self.cb_manager.switch_strategies_to_shadow_mode(
                tenant_id=tenant_id,
                user_id=user_id,
            )
            
            # Send notification
            await self.notification_service.send_daily_loss_alert(
                user_id=user_id,
                tenant_id=tenant_id,
                strategy_id=strategy_id,
                pnl_percentage=loss_event.metadata.get("pnl_percentage", 0.0),
                pnl_amount=loss_event.metadata.get("realized_pnl", 0.0),
            )
            
            # Override signal to HOLD
            adjusted_signal["action"] = "HOLD"
            adjusted_signal["confidence"] = 0.0
            adjusted_signal["allocation"] = 0.0
            circuit_breaker_triggered = True
            circuit_breaker_messages.append(loss_event.message)
            
            # Store event
            await self.cb_manager.handle_circuit_breaker_event(loss_event)
            
            # Early return - no point checking other breakers
            adjusted_signal["circuit_breaker_triggered"] = True
            adjusted_signal["circuit_breaker_messages"] = circuit_breaker_messages
            adjusted_signal["reasoning"] = (
                f"[CIRCUIT BREAKER] {loss_event.message}\n\n"
                f"Original reasoning: {reasoning}"
            )
            return adjusted_signal
        
        # 2. Check VIX Guard (reduce allocation in high volatility)
        if allocation > 0:
            adjusted_allocation, vix_event = self.cb_manager.check_vix_guard(
                allocation=allocation,
            )
            
            if vix_event:
                # Update event with user context
                vix_event = CircuitBreakerEvent(
                    breaker_type=vix_event.breaker_type,
                    timestamp=vix_event.timestamp,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    strategy_id=strategy_id,
                    severity=vix_event.severity,
                    message=vix_event.message,
                    metadata=vix_event.metadata,
                )
                
                logger.warning(f"⚠️  VIX GUARD: Reducing allocation from ${allocation:.2f} to ${adjusted_allocation:.2f}")
                
                adjusted_signal["allocation"] = adjusted_allocation
                adjusted_signal["original_allocation"] = allocation
                circuit_breaker_triggered = True
                circuit_breaker_messages.append(vix_event.message)
                
                # Send notification
                await self.notification_service.send_vix_guard_alert(
                    user_id=user_id,
                    vix_value=vix_event.metadata.get("vix_value", 0.0),
                    original_allocation=allocation,
                    adjusted_allocation=adjusted_allocation,
                )
                
                # Store event
                await self.cb_manager.handle_circuit_breaker_event(vix_event)
        
        # 3. Check Concentration Limit (downgrade BUY to HOLD if over-concentrated)
        if action == "BUY" and ticker:
            # Get positions from account snapshot
            positions = account_snapshot.get("positions", [])
            
            # Convert positions list to dict keyed by symbol
            positions_dict = {}
            for pos in positions:
                if isinstance(pos, dict):
                    symbol = pos.get("symbol", "")
                    if symbol:
                        positions_dict[symbol] = pos
            
            # Get total portfolio value
            equity_str = account_snapshot.get("equity", "0")
            try:
                total_portfolio_value = float(equity_str)
            except (ValueError, TypeError):
                total_portfolio_value = 0.0
            
            adjusted_action, concentration_event = self.cb_manager.check_concentration(
                ticker=ticker,
                signal_action=action,
                positions=positions_dict,
                total_portfolio_value=total_portfolio_value,
            )
            
            if concentration_event:
                # Update event with user context
                concentration_event = CircuitBreakerEvent(
                    breaker_type=concentration_event.breaker_type,
                    timestamp=concentration_event.timestamp,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    strategy_id=strategy_id,
                    severity=concentration_event.severity,
                    message=concentration_event.message,
                    metadata=concentration_event.metadata,
                )
                
                logger.warning(f"⚠️  CONCENTRATION LIMIT: Downgrading BUY to HOLD for {ticker}")
                
                adjusted_signal["action"] = adjusted_action
                adjusted_signal["original_action"] = action
                circuit_breaker_triggered = True
                circuit_breaker_messages.append(concentration_event.message)
                
                # Send notification
                await self.notification_service.send_concentration_alert(
                    user_id=user_id,
                    ticker=ticker,
                    concentration=concentration_event.metadata.get("concentration", 0.0),
                    ticker_value=concentration_event.metadata.get("ticker_value", 0.0),
                    portfolio_value=concentration_event.metadata.get("portfolio_value", 0.0),
                )
                
                # Store event
                await self.cb_manager.handle_circuit_breaker_event(concentration_event)
        
        # Add circuit breaker metadata to signal
        if circuit_breaker_triggered:
            adjusted_signal["circuit_breaker_triggered"] = True
            adjusted_signal["circuit_breaker_messages"] = circuit_breaker_messages
            
            # Prepend circuit breaker info to reasoning
            cb_prefix = "\n".join([f"[CIRCUIT BREAKER] {msg}" for msg in circuit_breaker_messages])
            adjusted_signal["reasoning"] = (
                f"{cb_prefix}\n\n"
                f"Original reasoning: {reasoning}"
            )
        
        return adjusted_signal


def create_strategy_wrapper(
    db_client: Any = None,
) -> StrategyCircuitBreakerWrapper:
    """
    Factory function to create a strategy circuit breaker wrapper.
    
    Args:
        db_client: Firestore client
    
    Returns:
        Configured StrategyCircuitBreakerWrapper instance
    """
    from .notifications import create_notification_service
    
    notification_service = create_notification_service(db_client=db_client)
    circuit_breaker_manager = CircuitBreakerManager(
        db_client=db_client,
        notification_service=notification_service,
    )
    
    return StrategyCircuitBreakerWrapper(
        circuit_breaker_manager=circuit_breaker_manager,
        notification_service=notification_service,
    )
