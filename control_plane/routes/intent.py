"""
Intent API routes.

GET /api/intents - Read last N option intents
POST /api/intent/submit - Submit ONE supervised paper option intent
POST /api/lockdown - Explicitly halt execution
"""

import logging
import os
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from control_plane.auth import require_auth
from control_plane.config import (
    is_execution_allowed,
    EXECUTION_CONFIRM_TOKEN,
    FIRESTORE_PROJECT_ID,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response Models ---

class SubmitIntentRequest(BaseModel):
    """Request to submit a paper option intent."""
    confirm_token: str = Field(..., description="Execution confirmation token")


class SubmitIntentResponse(BaseModel):
    """Response from submitting a paper option intent."""
    success: bool
    intent_id: str
    broker_order_id: Optional[str] = None
    status: str
    lockdown_applied: bool
    message: str


class LockdownResponse(BaseModel):
    """Response from lockdown operation."""
    success: bool
    execution_halted: bool
    timestamp: str
    message: str


class IntentHistoryItem(BaseModel):
    """Single intent history item."""
    intent_id: str
    strategy_id: str
    contract_symbol: str
    status: str
    timestamp: str


class IntentHistoryResponse(BaseModel):
    """Response containing intent history."""
    intents: list[IntentHistoryItem]
    count: int


# --- Helper Functions ---

def _get_firestore_client():
    """Get Firestore client (lazy import)."""
    try:
        import firebase_admin
        from firebase_admin import firestore
        
        # Initialize if needed
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()
        
        return firestore.client()
    except Exception as e:
        logger.error(f"Failed to initialize Firestore: {e}")
        return None


def _create_spy_atm_call_intent() -> dict:
    """
    Create a SPY ATM CALL option intent.
    
    This is a simplified version - in production, you'd fetch:
    - Current SPY price
    - Nearest ATM strike
    - Next Friday expiration
    - Proper contract symbol
    """
    now = datetime.now(timezone.utc).date()
    
    # Calculate next Friday
    days_ahead = (4 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    expiration_date = now + timedelta(days=days_ahead)
    
    # Example strike (in production, fetch current ATM)
    strike = Decimal("450.00")
    
    # Construct contract symbol (Alpaca format)
    # Format: SPY{YYMMDD}C{strike*1000:08d}
    exp_str = expiration_date.strftime("%y%m%d")
    strike_int = int(strike * 1000)
    contract_symbol = f"SPY{exp_str}C{strike_int:08d}"
    
    return {
        "intent_id": str(uuid.uuid4()),
        "strategy_id": "operator_control_plane",
        "symbol": "SPY",
        "side": "buy",
        "order_type": "market",
        "quantity": 1,  # ALWAYS 1
        "expiration": expiration_date.isoformat(),
        "strike": str(strike),
        "right": "call",
        "contract_symbol": contract_symbol,
        "underlying_price": "450.50",  # Example
        "strategy_source": "operator_manual",
    }


def _apply_lockdown():
    """
    Apply immediate lockdown by setting EXECUTION_HALTED=1.
    
    CRITICAL: This modifies the environment variable to prevent
    further executions until manually reset by operator.
    """
    os.environ["EXECUTION_HALTED"] = "1"
    logger.warning("LOCKDOWN APPLIED: EXECUTION_HALTED set to 1")


# --- API Routes ---

@router.get("/intents", response_model=IntentHistoryResponse)
async def get_intents(
    request: Request,
    limit: int = 10,
    user_email: str = Depends(require_auth),
):
    """
    Get last N option intents from Firestore (read-only).
    
    This endpoint only READS historical data - it never modifies anything.
    """
    logger.info(f"Intent history requested by operator: {user_email}, limit={limit}")
    
    db = _get_firestore_client()
    if not db:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firestore not available",
        )
    
    try:
        # Query last N intents from Firestore
        # Assuming intents are stored in a collection called "option_intents"
        intents_ref = db.collection("option_intents").order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(limit)
        
        docs = intents_ref.stream()
        
        intents = []
        for doc in docs:
            data = doc.to_dict()
            intents.append(IntentHistoryItem(
                intent_id=data.get("intent_id", doc.id),
                strategy_id=data.get("strategy_id", "unknown"),
                contract_symbol=data.get("contract_symbol", "unknown"),
                status=data.get("status", "unknown"),
                timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ))
        
        return IntentHistoryResponse(
            intents=intents,
            count=len(intents),
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch intent history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch intent history: {str(e)}",
        )


@router.post("/intent/submit", response_model=SubmitIntentResponse)
async def submit_intent(
    request: Request,
    req: SubmitIntentRequest,
    user_email: str = Depends(require_auth),
):
    """
    Submit ONE supervised paper option intent.
    
    SAFETY CONSTRAINTS:
    - Validates ALL 5 safety invariants
    - Calls existing process_option_intent()
    - Allows ONLY qty=1
    - Allows ONLY SPY ATM CALL
    - Executes ONCE
    - Immediately sets EXECUTION_HALTED=1
    
    This is the ONLY execution path in this service.
    """
    logger.warning(f"EXECUTION REQUESTED by operator: {user_email}")
    
    # 1. Validate confirmation token
    if req.confirm_token != EXECUTION_CONFIRM_TOKEN:
        logger.error(f"Invalid confirmation token from {user_email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid confirmation token",
        )
    
    # 2. Check ALL safety invariants
    allowed, reason = is_execution_allowed()
    if not allowed:
        logger.error(f"Execution blocked: {reason}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Execution not allowed: {reason}",
        )
    
    # 3. Create SPY ATM CALL intent (qty=1, hardcoded)
    intent_data = _create_spy_atm_call_intent()
    logger.info(f"Created intent: {intent_data['contract_symbol']}")
    
    # 4. Import and call existing execution path
    try:
        from backend.contracts.v2.trading import OptionOrderIntent, Side, OptionRight
        from backend.trading.execution.options_intent_gate import process_option_intent
        
        # Convert dict to OptionOrderIntent
        intent = OptionOrderIntent(
            intent_id=uuid.UUID(intent_data["intent_id"]),
            strategy_id=intent_data["strategy_id"],
            symbol=intent_data["symbol"],
            side=Side.BUY,
            order_type=intent_data["order_type"],
            quantity=intent_data["quantity"],
            expiration=date.fromisoformat(intent_data["expiration"]),
            strike=Decimal(intent_data["strike"]),
            right=OptionRight.CALL,
            contract_symbol=intent_data["contract_symbol"],
            options={
                "underlying_price": Decimal(intent_data["underlying_price"]),
                "strategy_source": intent_data["strategy_source"],
            },
        )
        
        logger.info(f"Calling process_option_intent for {intent.contract_symbol}")
        
        # Execute via existing gate
        result = process_option_intent(intent)
        
        # 5. IMMEDIATELY apply lockdown
        _apply_lockdown()
        
        # 6. Check result
        if result.blocked:
            logger.error(f"Intent blocked by gate: {result.reason}")
            return SubmitIntentResponse(
                success=False,
                intent_id=intent_data["intent_id"],
                broker_order_id=None,
                status="blocked",
                lockdown_applied=True,
                message=f"Intent blocked: {result.reason}",
            )
        
        # Extract execution details
        broker_order_id = None
        order_status = "unknown"
        
        if hasattr(result.execution_result, "stored") and result.execution_result.stored:
            stored = result.execution_result.stored
            broker_order_id = stored.get("broker_order_id")
            order_status = stored.get("status", "unknown")
        
        logger.warning(
            f"EXECUTION COMPLETED: intent={intent_data['intent_id']}, "
            f"broker_order={broker_order_id}, status={order_status}"
        )
        
        return SubmitIntentResponse(
            success=True,
            intent_id=intent_data["intent_id"],
            broker_order_id=broker_order_id,
            status=order_status,
            lockdown_applied=True,
            message="Intent submitted successfully. System locked down.",
        )
        
    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        
        # Apply lockdown even on failure
        _apply_lockdown()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution failed: {str(e)}. System locked down.",
        )


@router.post("/lockdown", response_model=LockdownResponse)
async def lockdown(
    request: Request,
    user_email: str = Depends(require_auth),
):
    """
    Explicitly halt execution by setting EXECUTION_HALTED=1.
    
    This is a safety mechanism to immediately stop all trading.
    """
    logger.warning(f"EXPLICIT LOCKDOWN requested by operator: {user_email}")
    
    _apply_lockdown()
    
    return LockdownResponse(
        success=True,
        execution_halted=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
        message="Execution halted. Set EXECUTION_HALTED=0 to re-enable.",
    )
