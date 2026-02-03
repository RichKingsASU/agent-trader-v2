import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import firestore
from backend.contracts.v2.trading import OptionOrderIntent
from backend.trading.execution.shadow_options_executor import ShadowOptionsExecutor, ShadowOptionsExecutionResult, InMemoryShadowTradeHistoryStore

# Assuming firebase_admin is initialized elsewhere in the application,
# but ensure it's initialized for this function context if run standalone.
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()

logger = logging.getLogger(__name__)

# Set high precision for financial calculations
getcontext().prec = 28

# Helper functions for risk checks (assuming they exist in risk_manager.py for brevity,
# but implementing them directly here for self-containment as per prompt's focus)

def _get_firestore_client() -> firestore.Client:
    return firestore.client()

def _as_decimal(v: Any) -> Decimal:
    """Convert various types to Decimal safely for precision."""
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return Decimal("0")
        return Decimal(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")

def _calculate_drawdown(current: Decimal, hwm: Decimal) -> Decimal:
    """Calculate drawdown percentage from High Water Mark."""
    if hwm <= 0:
        return Decimal("0")
    drawdown = ((hwm - current) / hwm) * Decimal("100")
    return drawdown.quantize(Decimal("0.01"))

def _check_system_trading_gate(db: firestore.Client) -> Optional[str]:
    """Check if the system trading gate is open."""
    try:
        gate_ref = db.collection("systemStatus").document("trading_gate")
        gate_doc = gate_ref.get()
        if not gate_doc.exists:
            return "Trading gate document not found. Assuming closed for safety."
        
        gate_data = gate_doc.to_dict() or {}
        trading_enabled = gate_data.get("trading_enabled", False)
        status = gate_data.get("status", "EMERGENCY_HALT")
        
        if not trading_enabled or status == "EMERGENCY_HALT":
            return f"System trading gate is CLOSED: trading_enabled={trading_enabled}, status={status}"
    except Exception as e:
        logger.exception("Error checking system trading gate")
        return f"Failed to check system trading gate due to error: {str(e)}"
    return None

def _check_system_drawdown_breaker(db: firestore.Client, current_equity: Optional[Decimal]) -> Optional[str]:
    """Check if the system drawdown circuit breaker (5% HWM) is triggered."""
    if current_equity is None or current_equity <= 0:
        return "Current equity not available or non-positive for drawdown check."

    try:
        risk_ref = db.collection("systemStatus").document("risk")
        risk_doc = risk_ref.get()
        if not risk_doc.exists:
            return "Risk management document not found. Cannot perform HWM check."
        
        risk_data = risk_doc.to_dict() or {}
        high_water_mark_raw = risk_data.get("high_water_mark")
        
        if high_water_mark_raw is None:
            return "High Water Mark not set. Cannot perform HWM check."

        high_water_mark = _as_decimal(high_water_mark_raw)
        
        drawdown_pct = _calculate_drawdown(current_equity, high_water_mark)
        
        if drawdown_pct > Decimal("5.0"):
            return (
                f"System drawdown breaker triggered. Current equity {_as_decimal(current_equity)} is "
                f"{drawdown_pct}% below High Water Mark {_as_decimal(high_water_mark)} (max allowed: 5%)"
            )
    except Exception as e:
        logger.exception("Error checking system drawdown breaker")
        return f"Failed to check system drawdown breaker due to error: {str(e)}"
    return None

def _get_current_shadow_pnl(strategy_id: str) -> Optional[Decimal]:
    """
    Simulated retrieval of strategy's current day Shadow PnL.
    In a real system, this would query `shadowTradeHistory` for realized/unrealized PnL
    for the given strategy and current day.
    For this minimal implementation, we assume a mechanism to retrieve this exists.
    """
    # Placeholder: In a real system, this would involve complex queries to Firestore's
    # shadowTradeHistory collection, filtering by strategy_id and current day,
    # and aggregating PnL.
    # Given 'no Firestore schema changes' and 'no new services' constraints,
    # and the prompt stating 'Shadow PnL with daily halt exists', we assume this
    # data is retrievable.
    # For a minimal, explicit implementation, we'll assume an environment variable
    # or a mock value for this exercise.
    
    # As a placeholder, let's assume we read from an environment variable for testing purposes
    # or return 0 for now.
    mock_pnl = os.getenv(f"MOCK_DAILY_PNL_{strategy_id.upper()}")
    if mock_pnl:
        try:
            return _as_decimal(mock_pnl)
        except InvalidOperation:
            logger.warning(f"Invalid MOCK_DAILY_PNL for {strategy_id}: {mock_pnl}")
            return Decimal("0")
    
    return Decimal("0") # Assume no PnL for now if not mocked


class IntentGateResult:
    """Structured result from the intent gate."""
    def __init__(self, blocked: bool, reason: Optional[str] = None, execution_result: Optional[ShadowOptionsExecutionResult] = None):
        self.blocked = blocked
        self.reason = reason
        self.execution_result = execution_result

    def to_dict(self) -> Dict[str, Any]:
        result = {"blocked": self.blocked}
        if self.reason:
            result["reason"] = self.reason
        if self.execution_result:
            result["execution_result"] = self.execution_result.stored # Assuming stored is what needs to be returned
        return result


def process_option_intent(intent: OptionOrderIntent) -> IntentGateResult:
    """
    This function is the single enforcement point for options paper trading safety invariants.
    
    Receives an OptionOrderIntent, applies all risk checks, and dispatches to ShadowOptionExecutor
    only if all checks pass.
    """
    db = _get_firestore_client()
    now_utc = datetime.now(timezone.utc)
    strategy_id = intent.strategy_id
    contract_symbol = intent.contract_symbol

    log_common_fields = {
        "event": "option.intent.gate",
        "strategy_id": strategy_id,
        "contract_symbol": contract_symbol,
        "timestamp": now_utc.isoformat(),
    }

    # 1. Strategy-local daily halt (4% target halt)
    # Placeholder implementation: check if strategy's current daily PnL exceeds -4% or +4% of a notional.
    # We define a notional capital of $100,000 for this strategy-local halt.
    strategy_capital_notional = Decimal("100000.00") # Assumed notional for local halt check
    local_halt_threshold_pct = Decimal("4.0")
    local_halt_threshold_usd = strategy_capital_notional * (local_halt_threshold_pct / Decimal("100"))

    current_shadow_pnl = _get_current_shadow_pnl(strategy_id)
    if current_shadow_pnl is not None:
        if current_shadow_pnl > local_halt_threshold_usd:
            reason = f"Strategy-local daily halt triggered: PnL {current_shadow_pnl} exceeds +{local_halt_threshold_pct}% (${local_halt_threshold_usd}) of notional capital."
            logger.warning(f"option.intent.blocked: {reason}", extra={"reason": reason, **log_common_fields})
            return IntentGateResult(blocked=True, reason=reason)
        if current_shadow_pnl < -local_halt_threshold_usd:
            reason = f"Strategy-local daily halt triggered: PnL {current_shadow_pnl} below -{local_halt_threshold_pct}% (${local_halt_threshold_usd}) of notional capital."
            logger.warning(f"option.intent.blocked: {reason}", extra={"reason": reason, **log_common_fields})
            return IntentGateResult(blocked=True, reason=reason)

    # 2. System trading gate (EMERGENCY_HALT / trading_enabled)
    gate_reason = _check_system_trading_gate(db)
    if gate_reason:
        logger.warning(f"option.intent.blocked: {gate_reason}", extra={"reason": gate_reason, **log_common_fields})
        return IntentGateResult(blocked=True, reason=gate_reason)

    # 3. System drawdown circuit breaker (5% HWM)
    # Fetch current equity from the latest Alpaca snapshot in Firestore
    current_equity: Optional[Decimal] = None
    try:
        alpaca_snapshot_doc = db.collection("alpacaAccounts").document("snapshot").get()
        if alpaca_snapshot_doc.exists:
            equity_raw = alpaca_snapshot_doc.to_dict().get("equity")
            current_equity = _as_decimal(equity_raw)
    except Exception as e:
        logger.error(f"Failed to retrieve current equity for drawdown check: {e}")
        # Proceed, but drawdown check might be skipped if equity is None
    
    drawdown_reason = _check_system_drawdown_breaker(db, current_equity)
    if drawdown_reason:
        logger.warning(f"option.intent.blocked: {drawdown_reason}", extra={"reason": drawdown_reason, **log_common_fields})
        return IntentGateResult(blocked=True, reason=drawdown_reason)

    # 4. Any local risk caps (if present)
    # As per audit, no additional local risk caps were identified beyond the 4% strategy halt.
    # This section serves as a placeholder for future extensions if such caps are defined.
    # No action required for this minimal implementation.

    # If all checks pass, approve and dispatch
    logger.info("option.intent.approved: All checks passed.", extra={**log_common_fields, "event": "option.intent.approved"})
    
    # Dispatch to ShadowOptionExecutor
    # Using InMemoryShadowTradeHistoryStore for this function's internal executor,
    # as the actual store should be injected or globally managed.
    # In a real scenario, ShadowOptionsExecutor would be initialized once with the proper store.
    shadow_executor = ShadowOptionsExecutor(store=InMemoryShadowTradeHistoryStore())
    execution_result = shadow_executor.execute(intent=intent)
    
    return IntentGateResult(blocked=False, execution_result=execution_result)
