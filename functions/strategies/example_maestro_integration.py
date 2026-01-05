"""
Example Integration: Maestro-Orchestrated Trading System

This example demonstrates how to integrate the Maestro orchestration layer
into a complete trading system with:
- Multi-strategy evaluation
- Sharpe-based allocation
- Systemic risk detection
- JIT Identity tracking
- AI summaries
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader
from functions.strategies.maestro_controller import MaestroController, AgentMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MaestroTradingSystem:
    """
    Complete trading system with Maestro orchestration.
    
    This class demonstrates best practices for integrating Maestro
    into a production trading system.
    """
    
    def __init__(
        self,
        db: firestore.Client,
        tenant_id: str = "default",
        uid: str = None,
        dry_run: bool = False
    ):
        """
        Initialize the trading system.
        
        Args:
            db: Firestore client
            tenant_id: Tenant identifier
            uid: User identifier
            dry_run: If True, log trades but don't execute
        """
        self.db = db
        self.tenant_id = tenant_id
        self.uid = uid
        self.dry_run = dry_run
        
        # Initialize Maestro-enabled StrategyLoader
        self.loader = StrategyLoader(db=db, tenant_id=tenant_id, uid=uid)
        
        logger.info(
            f"MaestroTradingSystem initialized: tenant={tenant_id}, "
            f"dry_run={dry_run}, strategies={len(self.loader.strategies)}"
        )
    
    async def run_trading_cycle(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Execute a complete trading cycle with Maestro orchestration.
        
        Steps:
        1. Evaluate all strategies
        2. Apply Maestro orchestration
        3. Execute trades (respecting modes and overrides)
        4. Log results
        
        Args:
            market_data: Current market data
            account_snapshot: Current account snapshot
            regime_data: Optional GEX regime data
            
        Returns:
            Dictionary with execution summary
        """
        logger.info("=" * 80)
        logger.info("🎭 Starting Maestro-Orchestrated Trading Cycle")
        logger.info("=" * 80)
        
        start_time = datetime.now(timezone.utc)
        
        # Step 1: Get orchestrated signals
        signals, maestro_decision = await self.loader.evaluate_all_strategies_with_maestro(
            market_data=market_data,
            account_snapshot=account_snapshot,
            regime=regime_data
        )
        
        # Step 2: Log Maestro summary
        if maestro_decision:
            logger.info(f"\n🎭 MAESTRO SUMMARY:")
            logger.info(f"   {maestro_decision.ai_summary}")
            
            if maestro_decision.systemic_risk_detected:
                logger.warning(f"\n⚠️ SYSTEMIC RISK OVERRIDE:")
                logger.warning(f"   {maestro_decision.systemic_risk_details}")
            
            # Log allocation decisions
            logger.info(f"\n📊 ALLOCATION DECISIONS:")
            for decision in maestro_decision.allocation_decisions:
                logger.info(
                    f"   {decision.strategy_name}: "
                    f"{decision.mode.value} "
                    f"(Sharpe: {decision.sharpe_ratio:.2f}, "
                    f"{decision.original_allocation:.0%} → {decision.final_allocation:.0%})"
                )
        
        # Step 3: Execute trades
        execution_summary = await self._execute_trades(
            signals=signals,
            account_snapshot=account_snapshot
        )
        
        # Step 4: Log summary
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(f"\n✅ TRADING CYCLE COMPLETE (took {duration:.2f}s)")
        logger.info(f"   Strategies evaluated: {execution_summary['total_strategies']}")
        logger.info(f"   Active: {execution_summary['active_count']}")
        logger.info(f"   Reduced: {execution_summary['reduced_count']}")
        logger.info(f"   Shadow: {execution_summary['shadow_count']}")
        logger.info(f"   Trades executed: {execution_summary['trades_executed']}")
        logger.info(f"   Signals overridden: {execution_summary['signals_overridden']}")
        logger.info("=" * 80)
        
        return {
            "session_id": maestro_decision.session_id if maestro_decision else None,
            "duration_seconds": duration,
            "execution_summary": execution_summary,
            "maestro_summary": maestro_decision.ai_summary if maestro_decision else None
        }
    
    async def _execute_trades(
        self,
        signals: Dict[str, Any],
        account_snapshot: Dict[str, Any]
    ) -> Dict[str, int]:
        """
        Execute trades based on orchestrated signals.
        
        Args:
            signals: Orchestrated signals from Maestro
            account_snapshot: Current account snapshot
            
        Returns:
            Execution summary statistics
        """
        buying_power = float(account_snapshot.get("buying_power", 0.0))
        
        summary = {
            "total_strategies": len(signals),
            "active_count": 0,
            "reduced_count": 0,
            "shadow_count": 0,
            "disabled_count": 0,
            "trades_executed": 0,
            "signals_overridden": 0
        }
        
        logger.info(f"\n💰 TRADE EXECUTION (Buying Power: ${buying_power:,.2f})")
        
        for strategy_name, signal in signals.items():
            if not isinstance(signal, dict):
                logger.warning(f"   {strategy_name}: Invalid signal format")
                continue
            
            # Track mode distribution
            mode = signal.get("mode", "ACTIVE")
            if mode == "ACTIVE":
                summary["active_count"] += 1
            elif mode == "REDUCED":
                summary["reduced_count"] += 1
            elif mode == "SHADOW_MODE":
                summary["shadow_count"] += 1
            elif mode == "DISABLED":
                summary["disabled_count"] += 1
            
            # Check for overrides
            if "override_reason" in signal:
                summary["signals_overridden"] += 1
                logger.warning(
                    f"   ⚠️ {strategy_name}: OVERRIDDEN - {signal['override_reason']}"
                )
            
            # Handle shadow mode
            if mode == "SHADOW_MODE":
                logger.info(f"   📝 {strategy_name}: SHADOW MODE - Paper trading only")
                await self._log_shadow_trade(strategy_name, signal)
                continue
            
            # Handle disabled
            if mode == "DISABLED":
                logger.info(f"   🚫 {strategy_name}: DISABLED - Skipping")
                continue
            
            # Execute trade
            action = signal.get("action", "HOLD")
            allocation = signal.get("allocation", 0.0)
            
            if action == "HOLD" or allocation <= 0:
                logger.info(f"   ⏸️ {strategy_name}: HOLD (allocation: {allocation:.2%})")
                continue
            
            # Calculate trade size
            trade_amount = buying_power * allocation
            
            logger.info(
                f"   {'🔴' if action == 'SELL' else '🟢'} {strategy_name}: "
                f"{action} ${trade_amount:,.2f} "
                f"(allocation: {allocation:.2%}, mode: {mode})"
            )
            
            # Execute (or simulate if dry_run)
            if self.dry_run:
                logger.info(f"      [DRY RUN - Trade not executed]")
            else:
                await self._execute_single_trade(
                    strategy_name=strategy_name,
                    signal=signal,
                    amount=trade_amount
                )
            
            summary["trades_executed"] += 1
        
        return summary
    
    async def _execute_single_trade(
        self,
        strategy_name: str,
        signal: Dict[str, Any],
        amount: float
    ) -> None:
        """
        Execute a single trade with JIT Identity tracking.
        
        Args:
            strategy_name: Name of the strategy
            signal: Signal with JIT Identity
            amount: Dollar amount to trade
        """
        try:
            # Extract JIT Identity
            agent_id = signal.get("agent_id")
            nonce = signal.get("nonce")
            session_id = signal.get("session_id")
            
            # Log trade with identity
            trade_log = {
                "timestamp": firestore.SERVER_TIMESTAMP,
                "strategy_name": strategy_name,
                "action": signal["action"],
                "ticker": signal.get("ticker", "UNKNOWN"),
                "amount": amount,
                "allocation": signal.get("allocation", 0.0),
                "mode": signal.get("mode", "ACTIVE"),
                
                # JIT Identity
                "agent_id": agent_id,
                "nonce": nonce,
                "session_id": session_id,
                
                # Additional context
                "reasoning": signal.get("reasoning", ""),
                "confidence": signal.get("confidence", 0.0),
                "original_allocation": signal.get("original_allocation"),
                "weight_multiplier": signal.get("weight_multiplier", 1.0)
            }
            
            # Store in Firestore
            trade_ref = self.db.collection("tenants") \
                .document(self.tenant_id) \
                .collection("trade_log") \
                .document()
            
            trade_ref.set(trade_log)
            
            logger.info(
                f"      ✅ Trade logged with identity: "
                f"agent_id={agent_id}, nonce={nonce[:8]}..."
            )
            
            # TODO: Integrate with actual broker API (Alpaca, etc.)
            # alpaca_api.submit_order(...)
            
        except Exception as e:
            logger.error(f"      ❌ Trade execution failed: {e}", exc_info=True)
    
    async def _log_shadow_trade(
        self,
        strategy_name: str,
        signal: Dict[str, Any]
    ) -> None:
        """
        Log a shadow trade (paper trading only).
        
        Args:
            strategy_name: Name of the strategy
            signal: Signal data
        """
        try:
            shadow_log = {
                "timestamp": firestore.SERVER_TIMESTAMP,
                "strategy_name": strategy_name,
                "action": signal["action"],
                "ticker": signal.get("ticker", "UNKNOWN"),
                "mode": "SHADOW_MODE",
                "reasoning": signal.get("reasoning", ""),
                "sharpe_ratio": signal.get("sharpe_ratio", 0.0),
                
                # JIT Identity
                "agent_id": signal.get("agent_id"),
                "nonce": signal.get("nonce"),
                "session_id": signal.get("session_id")
            }
            
            # Store in shadow P&L collection
            shadow_ref = self.db.collection("tenants") \
                .document(self.tenant_id) \
                .collection("shadow_pnl") \
                .document()
            
            shadow_ref.set(shadow_log)
            
        except Exception as e:
            logger.error(f"Failed to log shadow trade: {e}")
    
    async def get_maestro_insights(
        self,
        lookback_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get Maestro insights from recent orchestration decisions.
        
        Args:
            lookback_hours: How many hours to look back
            
        Returns:
            Dictionary with insights and statistics
        """
        from datetime import timedelta
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        
        # Query orchestration logs
        logs = self.db.collection("systemStatus") \
            .document("orchestration_logs") \
            .collection("logs") \
            .where("timestamp", ">=", cutoff) \
            .order_by("timestamp", direction=firestore.Query.DESCENDING) \
            .stream()
        
        insights = {
            "total_decisions": 0,
            "systemic_risk_events": 0,
            "strategies_reduced": set(),
            "strategies_shadowed": set(),
            "recent_summaries": []
        }
        
        for log in logs:
            data = log.to_dict()
            insights["total_decisions"] += 1
            
            if data.get("systemic_risk_detected"):
                insights["systemic_risk_events"] += 1
            
            for decision in data.get("allocation_decisions", []):
                if decision["mode"] == "REDUCED":
                    insights["strategies_reduced"].add(decision["strategy_name"])
                elif decision["mode"] == "SHADOW_MODE":
                    insights["strategies_shadowed"].add(decision["strategy_name"])
            
            if data.get("ai_summary"):
                insights["recent_summaries"].append({
                    "timestamp": data["timestamp"],
                    "summary": data["ai_summary"]
                })
        
        # Convert sets to lists for JSON serialization
        insights["strategies_reduced"] = list(insights["strategies_reduced"])
        insights["strategies_shadowed"] = list(insights["strategies_shadowed"])
        
        return insights


# Example usage
async def main():
    """Example main function demonstrating Maestro integration."""
    
    # Initialize Firestore (assumes firebase_admin is initialized)
    import firebase_admin
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    
    db = firestore.client()
    
    # Create trading system with Maestro
    trading_system = MaestroTradingSystem(
        db=db,
        tenant_id="example-tenant",
        uid="user123",
        dry_run=True  # Set to False for real trading
    )
    
    # Mock market data
    market_data = {
        "SPY": {
            "price": 450.00,
            "volume": 1000000,
            "change_percent": 0.5
        },
        "QQQ": {
            "price": 380.00,
            "volume": 800000,
            "change_percent": 0.3
        }
    }
    
    # Mock account snapshot
    account_snapshot = {
        "equity": "100000.00",
        "buying_power": "50000.00",
        "cash": "40000.00",
        "positions": []
    }
    
    # Run trading cycle
    result = await trading_system.run_trading_cycle(
        market_data=market_data,
        account_snapshot=account_snapshot
    )
    
    print(f"\n{'=' * 80}")
    print(f"EXECUTION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Session ID: {result['session_id']}")
    print(f"Duration: {result['duration_seconds']:.2f}s")
    print(f"\nMaestro Summary:")
    print(f"{result['maestro_summary']}")
    
    # Get insights
    insights = await trading_system.get_maestro_insights(lookback_hours=24)
    
    print(f"\n{'=' * 80}")
    print(f"24-HOUR MAESTRO INSIGHTS")
    print(f"{'=' * 80}")
    print(f"Total decisions: {insights['total_decisions']}")
    print(f"Systemic risk events: {insights['systemic_risk_events']}")
    print(f"Strategies with reduced allocation: {insights['strategies_reduced']}")
    print(f"Strategies in shadow mode: {insights['strategies_shadowed']}")
    
    if insights['recent_summaries']:
        print(f"\nRecent summaries:")
        for summary in insights['recent_summaries'][:3]:
            print(f"  • {summary['summary']}")


if __name__ == "__main__":
    asyncio.run(main())
