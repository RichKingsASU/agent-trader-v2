"""
BaseStrategy wrapper with integrated circuit breakers.

This module provides a wrapped version of BaseStrategy that automatically
applies circuit breakers to all strategy evaluations.

Usage in functions/main.py:
    from backend.risk.base_strategy_wrapper import evaluate_strategy_with_circuit_breakers
    
    signal = await evaluate_strategy_with_circuit_breakers(
        strategy=strategy_instance,
        market_data=market_data,
        account_snapshot=account_snapshot,
        user_id=user_id,
        tenant_id=tenant_id,
        strategy_id=strategy_id,
        db=db,
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .circuit_breakers import CircuitBreakerManager
from .notifications import NotificationService
from .strategy_integration import StrategyCircuitBreakerWrapper

logger = logging.getLogger(__name__)


async def evaluate_strategy_with_circuit_breakers(
    *,
    strategy: Any,
    market_data: Dict[str, Any],
    account_snapshot: Dict[str, Any],
    regime: Optional[str] = None,
    user_id: str,
    tenant_id: str,
    strategy_id: str,
    db: Any,
    trades_today: Optional[List[Any]] = None,
    starting_equity: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Evaluate a strategy with circuit breaker protections.
    
    This is the main entry point for executing strategies with circuit breakers.
    It wraps the standard strategy.evaluate() method and applies all risk controls.
    
    Args:
        strategy: Strategy instance to evaluate
        market_data: Current market data
        account_snapshot: Current account state
        regime: Optional market regime
        user_id: User ID
        tenant_id: Tenant ID
        strategy_id: Strategy ID
        db: Firestore client
        trades_today: List of trades executed today (optional, will fetch if not provided)
        starting_equity: Starting equity for the day (optional, will use current equity if not provided)
    
    Returns:
        Trading signal with circuit breaker adjustments applied
    """
    # Step 1: Evaluate the strategy normally
    try:
        if hasattr(strategy, 'evaluate'):
            # Check if evaluate is async or sync
            import asyncio
            if asyncio.iscoroutinefunction(strategy.evaluate):
                signal = await strategy.evaluate(market_data, account_snapshot, regime)
            else:
                signal = strategy.evaluate(market_data, account_snapshot, regime)
        else:
            logger.error(f"Strategy {strategy_id} has no evaluate method")
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": "Strategy has no evaluate method",
            }
        
        # Convert TradingSignal to dict if needed
        if hasattr(signal, 'to_dict'):
            signal = signal.to_dict()
        elif not isinstance(signal, dict):
            logger.error(f"Strategy {strategy_id} returned invalid signal type: {type(signal)}")
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": "Strategy returned invalid signal",
            }
    
    except Exception as e:
        logger.error(f"Error evaluating strategy {strategy_id}: {e}", exc_info=True)
        return {
            "action": "HOLD",
            "confidence": 0.0,
            "reasoning": f"Strategy evaluation failed: {str(e)}",
        }
    
    # Step 2: Fetch trades and starting equity if not provided
    if trades_today is None:
        trades_today = await _fetch_trades_today(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            strategy_id=strategy_id,
        )
    
    if starting_equity is None:
        # Use current equity as a fallback
        equity_str = account_snapshot.get("equity", "0")
        try:
            starting_equity = float(equity_str)
        except (ValueError, TypeError):
            starting_equity = 0.0
    
    # Step 3: Apply circuit breakers
    try:
        wrapper = StrategyCircuitBreakerWrapper(
            circuit_breaker_manager=CircuitBreakerManager(
                db_client=db,
                notification_service=NotificationService(db_client=db),
            ),
            notification_service=NotificationService(db_client=db),
        )
        
        adjusted_signal = await wrapper.evaluate_with_circuit_breakers(
            tenant_id=tenant_id,
            user_id=user_id,
            strategy_id=strategy_id,
            signal=signal,
            account_snapshot=account_snapshot,
            trades_today=trades_today,
            starting_equity=starting_equity,
        )
        
        return adjusted_signal
    
    except Exception as e:
        logger.error(f"Error applying circuit breakers: {e}", exc_info=True)
        # Return original signal if circuit breaker application fails
        return signal


async def _fetch_trades_today(
    *,
    db: Any,
    tenant_id: str,
    user_id: str,
    strategy_id: str,
) -> List[Any]:
    """
    Fetch today's trades from Firestore.
    
    Args:
        db: Firestore client
        tenant_id: Tenant ID
        user_id: User ID
        strategy_id: Strategy ID
    
    Returns:
        List of LedgerTrade objects for today
    """
    from ..ledger.models import LedgerTrade
    
    try:
        # Get start of today (UTC)
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        # Query Firestore for today's trades
        trades_ref = (
            db.collection("tenants")
            .document(tenant_id)
            .collection("ledger_trades")
        )
        
        # Filter by user, strategy, and timestamp
        query = (
            trades_ref
            .where("uid", "==", user_id)
            .where("strategy_id", "==", strategy_id)
            .where("ts", ">=", today_start)
        )
        
        trade_docs = query.stream()
        
        # Convert to LedgerTrade objects
        trades = []
        for doc in trade_docs:
            data = doc.to_dict()
            try:
                trade = LedgerTrade(
                    tenant_id=data.get("tenant_id", tenant_id),
                    uid=data.get("uid", user_id),
                    strategy_id=data.get("strategy_id", strategy_id),
                    run_id=data.get("run_id", ""),
                    symbol=data.get("symbol", ""),
                    side=data.get("side", "buy"),
                    qty=data.get("qty", 0),
                    price=data.get("price", 0),
                    ts=data.get("ts", datetime.now(timezone.utc)),
                    order_id=data.get("order_id"),
                    broker_fill_id=data.get("broker_fill_id"),
                    fees=data.get("fees", 0.0),
                    slippage=data.get("slippage", 0.0),
                    account_id=data.get("account_id"),
                )
                trades.append(trade)
            except Exception as e:
                logger.error(f"Error parsing trade document {doc.id}: {e}")
                continue
        
        logger.info(f"Fetched {len(trades)} trades for today")
        return trades
    
    except Exception as e:
        logger.error(f"Error fetching today's trades: {e}", exc_info=True)
        return []


async def get_starting_equity_for_day(
    *,
    db: Any,
    tenant_id: str,
    user_id: str,
) -> Optional[float]:
    """
    Get the starting equity for the current trading day.
    
    This fetches the account snapshot from the beginning of the day
    or uses the previous day's closing equity.
    
    Args:
        db: Firestore client
        tenant_id: Tenant ID
        user_id: User ID
    
    Returns:
        Starting equity or None if not found
    """
    try:
        # Check if we have a daily snapshot
        today = datetime.now(timezone.utc).date()
        snapshot_ref = (
            db.collection("tenants")
            .document(tenant_id)
            .collection("users")
            .document(user_id)
            .collection("daily_snapshots")
            .document(today.isoformat())
        )
        
        doc = snapshot_ref.get()
        if doc.exists:
            data = doc.to_dict()
            equity = data.get("starting_equity")
            if equity is not None:
                return float(equity)
        
        # Fallback: get current equity from account snapshot
        account_ref = (
            db.collection("users")
            .document(user_id)
            .collection("alpacaAccounts")
            .document("snapshot")
        )
        
        account_doc = account_ref.get()
        if account_doc.exists:
            account_data = account_doc.to_dict()
            equity_str = account_data.get("equity", "0")
            try:
                return float(equity_str)
            except (ValueError, TypeError):
                return None
        
        return None
    
    except Exception as e:
        logger.error(f"Error fetching starting equity: {e}", exc_info=True)
        return None
