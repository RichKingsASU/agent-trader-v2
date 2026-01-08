from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import requests
import os
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging

from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.common.kill_switch import get_kill_switch_state
from google.cloud import firestore

from backend.risk.loss_acceleration_guard import LossAccelerationGuard

from ..db import build_raw_order, insert_paper_order
from ..models import PaperOrderCreate

router = APIRouter()
logger = logging.getLogger(__name__)

RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8002")

class TradeRequest(BaseModel):
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: float = None


def get_shadow_mode_flag() -> bool:
    """
    Check if shadow mode is enabled in Firestore systemStatus/config.
    
    Fail-safe: Returns True (shadow mode ON) on any errors to ensure
    the system defaults to safe simulation mode.
    
    Returns:
        bool: True if shadow mode is enabled, False otherwise
    """
    try:
        db = get_firestore_client()
        config_doc = with_firestore_retry(
            lambda: db.collection("systemStatus").document("config").get()
        )
        
        if config_doc.exists:
            data = config_doc.to_dict()
            is_shadow = data.get("is_shadow_mode", True)  # Default to True if field missing
            logger.info(f"Shadow mode flag retrieved: {is_shadow}")
            return is_shadow
        else:
            logger.warning("systemStatus/config document not found. Defaulting to shadow mode = True")
            return True
            
    except Exception as e:
        logger.error(f"Error reading shadow mode flag from Firestore: {e}. Defaulting to shadow mode = True")
        return True


def get_current_price(symbol: str) -> Decimal:
    """
    Fetch current price from live_quotes collection for shadow fills.
    
    Args:
        symbol: Stock symbol
        
    Returns:
        Decimal: Current price, or 0 if not found
    """
    try:
        db = get_firestore_client()
        quote_doc = with_firestore_retry(
            lambda: db.collection("live_quotes").document(symbol).get()
        )
        
        if quote_doc.exists:
            data = quote_doc.to_dict()
            # Use mid price (average of bid/ask) if available, otherwise use 'price' field
            bid = data.get("bid")
            ask = data.get("ask")
            if bid is not None and ask is not None:
                mid_price = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")
                return mid_price
            elif data.get("price"):
                return Decimal(str(data["price"]))
        
        logger.warning(f"No live quote found for {symbol}, returning 0")
        return Decimal("0")
        
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return Decimal("0")


def create_shadow_trade(trade_request: TradeRequest, ctx: TenantContext) -> dict:
    """
    Create a synthetic shadow trade and log it to user-scoped shadowTradeHistory collection.
    
    Path: users/{uid}/shadowTradeHistory/{shadow_id}
    
    Args:
        trade_request: Trade request details
        ctx: Tenant context
        
    Returns:
        dict: Shadow trade record
    """
    try:
        db = get_firestore_client()
        shadow_id = str(uuid4())
        
        # Get current price for fill simulation
        fill_price = get_current_price(trade_request.symbol)
        
        # Calculate quantity using Decimal for precision
        if trade_request.quantity:
            qty = Decimal(str(trade_request.quantity))
        else:
            # Calculate from notional
            if fill_price > 0:
                qty = Decimal(str(trade_request.notional)) / fill_price
            else:
                qty = Decimal("0")
        
        # Create shadow trade record
        shadow_trade = {
            "shadow_id": shadow_id,
            "uid": ctx.uid,
            "tenant_id": ctx.tenant_id,
            "broker_account_id": str(trade_request.broker_account_id),
            "strategy_id": str(trade_request.strategy_id),
            "symbol": trade_request.symbol,
            "instrument_type": trade_request.instrument_type,
            "side": trade_request.side,
            "order_type": trade_request.order_type,
            "time_in_force": trade_request.time_in_force,
            "notional": str(trade_request.notional),
            "quantity": str(qty),
            "entry_price": str(fill_price),  # Using 'entry_price' for consistency with P&L tracking
            "status": "OPEN",  # Using 'OPEN' status to enable P&L tracking in heartbeat
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_at_iso": datetime.now(timezone.utc).isoformat(),
            # P&L tracking fields (initialized)
            "current_pnl": "0.00",
            "pnl_percent": "0.00",
            "current_price": str(fill_price),
            "last_updated": firestore.SERVER_TIMESTAMP,
        }
        
        # Write to user-scoped shadowTradeHistory collection
        with_firestore_retry(
            lambda: db.collection("users")
            .document(ctx.uid)
            .collection("shadowTradeHistory")
            .document(shadow_id)
            .set(shadow_trade, merge=False)
        )
        
        logger.info(f"Shadow trade created: {shadow_id} - {trade_request.symbol} {trade_request.side} qty={qty} @ ${fill_price}")
        
        return shadow_trade
        
    except Exception as e:
        logger.error(f"Error creating shadow trade: {e}")
        raise
    
class CloseShadowTradeRequest(BaseModel):
    shadow_id: str
    exit_reason: str = "Manual close"


@router.post("/trades/execute", status_code=201)
def execute_trade(trade_request: TradeRequest, request: Request):
    """
    Execute a trade with shadow mode support.
    
    If shadow mode is enabled (is_shadow_mode == True):
    - Create a synthetic order with SHADOW_FILLED status
    - Log to shadowTradeHistory collection
    - Do NOT contact Alpaca broker
    
    If shadow mode is disabled (is_shadow_mode == False):
    - Proceed with live Alpaca order submission
    - (Current implementation uses paper orders; will be extended for live trading)
    
    Fail-safe: On any error reading the shadow mode flag, defaults to shadow mode = True
    """
    ctx: TenantContext = get_tenant_context(request)

    # --- Loss acceleration guardrails (independent of strategy logic) ---
    # Enforces:
    # - rolling drawdown velocity monitoring (loss/time)
    # - automatic throttling (HTTP 429 + Retry-After)
    # - automatic pausing (disable trading + switch strategies to SHADOW_MODE)
    try:
        db = get_firestore_client()
        now = datetime.now(timezone.utc)

        # 1) Honor existing pause state (with optional auto-resume).
        trading_status_ref = (
            db.collection("users").document(ctx.uid).collection("status").document("trading")
        )
        trading_status_doc = with_firestore_retry(lambda: trading_status_ref.get())
        if trading_status_doc.exists:
            st = trading_status_doc.to_dict() or {}
            enabled = bool(st.get("enabled", True))
            disabled_until = st.get("disabled_until")
            if not enabled:
                if isinstance(disabled_until, datetime) and now >= disabled_until.astimezone(timezone.utc):
                    # Auto-resume after cooldown.
                    with_firestore_retry(
                        lambda: trading_status_ref.set(
                            {
                                "enabled": True,
                                "disabled_by": None,
                                "disabled_at": None,
                                "disabled_until": None,
                                "reason": None,
                                "last_resumed_at": firestore.SERVER_TIMESTAMP,
                            },
                            merge=True,
                        )
                    )
                else:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "trading_paused",
                            "message": st.get("reason") or "Trading is paused by risk guardrails.",
                            "disabled_until": disabled_until.isoformat() if isinstance(disabled_until, datetime) else None,
                        },
                    )

        # 2) Honor existing throttle state.
        throttle_ref = (
            db.collection("users").document(ctx.uid).collection("status").document("trade_throttle")
        )
        throttle_doc = with_firestore_retry(lambda: throttle_ref.get())
        if throttle_doc.exists:
            td = throttle_doc.to_dict() or {}
            next_allowed_at = td.get("next_allowed_at")
            if isinstance(next_allowed_at, datetime) and now < next_allowed_at.astimezone(timezone.utc):
                retry_after_s = max(1, int((next_allowed_at.astimezone(timezone.utc) - now).total_seconds()))
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "trade_throttled",
                        "message": td.get("reason") or "Trade throttled due to loss acceleration.",
                        "retry_after_seconds": retry_after_s,
                        "next_allowed_at": next_allowed_at.isoformat(),
                    },
                    headers={"Retry-After": str(retry_after_s)},
                )

        # 3) Compute drawdown velocity and apply conservative guardrails.
        guard = LossAccelerationGuard()
        decision = guard.decide(uid=ctx.uid)
        m = decision.metrics
        metrics_payload = (
            {
                "window_seconds": m.window_seconds,
                "points_used": m.points_used,
                "hwm_equity": m.hwm_equity,
                "current_equity": m.current_equity,
                "current_drawdown_pct": m.current_drawdown_pct,
                "velocity_pct_per_min": m.velocity_pct_per_min,
                "window_start": m.window_start.isoformat(),
                "window_end": m.window_end.isoformat(),
            }
            if m is not None
            else None
        )

        if decision.action == "pause" and decision.pause_until is not None:
            # Persist pause state (auto-resume supported by disabled_until).
            pause_until = decision.pause_until.astimezone(timezone.utc)
            with_firestore_retry(
                lambda: trading_status_ref.set(
                    {
                        "enabled": False,
                        "disabled_by": "loss_acceleration_guard",
                        "disabled_at": firestore.SERVER_TIMESTAMP,
                        "disabled_until": pause_until,
                        "reason": "Paused due to dangerous loss acceleration (drawdown velocity).",
                        "metrics": metrics_payload,
                    },
                    merge=True,
                )
            )

            # Switch all active strategies to SHADOW_MODE (best-effort).
            try:
                strategies_ref = (
                    db.collection("tenants")
                    .document(ctx.tenant_id)
                    .collection("users")
                    .document(ctx.uid)
                    .collection("strategies")
                )
                for doc in strategies_ref.where("status", "==", "active").stream():
                    strategies_ref.document(doc.id).set(
                        {
                            "execution_mode": "SHADOW_MODE",
                            "shadow_mode_reason": "loss_acceleration_pause",
                            "shadow_mode_activated_at": firestore.SERVER_TIMESTAMP,
                        },
                        merge=True,
                    )
            except Exception:
                logger.exception("loss_accel: failed to switch strategies to SHADOW_MODE (best-effort)")

            raise HTTPException(
                status_code=409,
                detail={
                    "error": "loss_acceleration_pause",
                    "message": "Trading paused due to dangerous loss acceleration.",
                    "paused_until": pause_until.isoformat(),
                    "metrics": metrics_payload,
                },
            )

        if decision.action == "throttle" and decision.retry_after_seconds is not None:
            # Persist throttle state and reject with Retry-After (conservative).
            next_allowed = now + timedelta(seconds=int(decision.retry_after_seconds))
            with_firestore_retry(
                lambda: throttle_ref.set(
                    {
                        "next_allowed_at": next_allowed,
                        "reason": "Throttled due to elevated drawdown velocity (loss acceleration).",
                        "throttled_at": firestore.SERVER_TIMESTAMP,
                        "metrics": metrics_payload,
                    },
                    merge=True,
                )
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "loss_acceleration_throttle",
                    "message": "Trade throttled due to loss acceleration.",
                    "retry_after_seconds": int(decision.retry_after_seconds),
                    "next_allowed_at": next_allowed.isoformat(),
                    "metrics": metrics_payload,
                },
                headers={"Retry-After": str(int(decision.retry_after_seconds))},
            )
    except HTTPException:
        raise
    except Exception as e:
        # Fail-safe: if guardrail evaluation fails, do NOT block trading here.
        logger.warning("loss_accel: guard evaluation failed (non-fatal): %s", e)
    
    # Check shadow mode flag (fail-safe: defaults to True)
    is_shadow_mode = get_shadow_mode_flag()
    logger.info(f"Executing trade in {'SHADOW' if is_shadow_mode else 'LIVE'} mode")

    # Global kill switch: block any non-shadow ("live") execution path.
    enabled, source = get_kill_switch_state()
    if enabled and not is_shadow_mode:
        logger.warning("kill_switch_active refusing_live_trade source=%s symbol=%s side=%s", source, trade_request.symbol, trade_request.side)
        raise HTTPException(
            status_code=409,
            detail={"error": "kill_switch_enabled", "source": source, "message": "Execution is globally halted."},
        )
    
    # Risk check (always performed regardless of mode)
    risk_check_payload = {
        "broker_account_id": str(trade_request.broker_account_id),
        "strategy_id": str(trade_request.strategy_id),
        "symbol": trade_request.symbol,
        "notional": str(trade_request.notional),
        "side": trade_request.side,
        "current_open_positions": 0,
        "current_trades_today": 0,
        "current_day_loss": "0.0",
        "current_day_drawdown": "0.0",
    }

    try:
        response = requests.post(
            f"{RISK_SERVICE_URL}/risk/check-trade",
            json=risk_check_payload,
            headers={"Authorization": request.headers.get("Authorization", "")},
        )
        response.raise_for_status()
        risk_result = response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Risk service request failed: {e}")

    if not risk_result.get("allowed"):
        raise HTTPException(status_code=400, detail=f"Trade not allowed by risk service: {risk_result.get('reason')}")

    # SHADOW MODE: Create synthetic order without contacting broker
    if is_shadow_mode:
        try:
            shadow_trade = create_shadow_trade(trade_request, ctx)
            logger.info(f"Shadow trade executed successfully: {shadow_trade['shadow_id']}")
            
            # Return shadow trade in a format similar to paper order
            return {
                "id": shadow_trade["shadow_id"],
                "status": "OPEN",
                "mode": "shadow",
                "created_at": shadow_trade["created_at_iso"],
                "symbol": shadow_trade["symbol"],
                "side": shadow_trade["side"],
                "quantity": shadow_trade["quantity"],
                "entry_price": shadow_trade["entry_price"],
                "current_pnl": shadow_trade["current_pnl"],
                "pnl_percent": shadow_trade["pnl_percent"],
                "message": "Trade executed in SHADOW MODE (simulation only, no broker contact). P&L will be tracked in real-time.",
            }
        except Exception as e:
            logger.exception(f"Failed to create shadow trade: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create shadow trade: {e}")
    
    # LIVE MODE: Proceed with actual broker order (paper order for now)
    else:
        try:
            logical_order = {
                "uid": ctx.uid,
                "broker_account_id": str(trade_request.broker_account_id),
                "strategy_id": str(trade_request.strategy_id),
                "symbol": trade_request.symbol,
                "instrument_type": trade_request.instrument_type,
                "side": trade_request.side,
                "order_type": trade_request.order_type,
                "time_in_force": trade_request.time_in_force,
                "notional": trade_request.notional,
                "quantity": trade_request.quantity,
            }
            payload = PaperOrderCreate(
                uid=ctx.uid,
                broker_account_id=trade_request.broker_account_id,
                strategy_id=trade_request.strategy_id,
                symbol=trade_request.symbol,
                instrument_type=trade_request.instrument_type,
                side=trade_request.side,
                order_type=trade_request.order_type,
                time_in_force=trade_request.time_in_force,
                notional=trade_request.notional,
                quantity=trade_request.quantity,
                risk_allowed=True,
                risk_scope=risk_result.get("scope"),
                risk_reason=risk_result.get("reason") or "Allowed by risk check",
                raw_order=build_raw_order(logical_order),
                status="simulated",  # TODO: Change to "submitted" when live Alpaca integration is complete
            )
            
            result = insert_paper_order(tenant_id=ctx.tenant_id, payload=payload)
            logger.info(f"Live/Paper trade executed successfully: {result.id}")
            return result
            
        except Exception as e:
            logger.exception(f"Failed to insert paper order: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to insert paper order: {e}")


@router.post("/trades/close-shadow", status_code=200)
def close_shadow_trade(close_request: CloseShadowTradeRequest, request: Request):
    """
    Close a shadow trade and trigger AI analysis.
    
    This endpoint:
    1. Updates the shadow trade status to CLOSED
    2. Records exit_price using current market price
    3. Calculates final P&L
    4. Triggers the Cloud Function AI analysis (via Firestore trigger)
    
    Args:
        close_request: Shadow trade ID and optional exit reason
        
    Returns:
        Updated shadow trade with CLOSED status and final P&L
    """
    ctx: TenantContext = get_tenant_context(request)
    
    try:
        db = get_firestore_client()
        shadow_id = close_request.shadow_id
        
        # Get the shadow trade document
        shadow_ref = db.collection("shadowTradeHistory").document(shadow_id)
        shadow_doc = with_firestore_retry(lambda: shadow_ref.get())
        
        if not shadow_doc.exists:
            raise HTTPException(status_code=404, detail=f"Shadow trade {shadow_id} not found")
        
        shadow_data = shadow_doc.to_dict()
        
        # Verify ownership
        if shadow_data.get("uid") != ctx.uid:
            raise HTTPException(status_code=403, detail="Not authorized to close this trade")
        
        # Check if already closed
        if shadow_data.get("status") == "CLOSED":
            raise HTTPException(status_code=400, detail="Trade is already closed")
        
        # Get current exit price
        symbol = shadow_data.get("symbol")
        exit_price = get_current_price(symbol)
        
        if exit_price == Decimal("0"):
            raise HTTPException(
                status_code=500, 
                detail=f"Unable to get current price for {symbol}. Please try again."
            )
        
        # Calculate final P&L (use existing current_pnl as the final realized P&L)
        final_pnl = shadow_data.get("current_pnl", "0.00")
        pnl_percent = shadow_data.get("pnl_percent", "0.00")
        
        # Update the document to CLOSED status
        # This will trigger the Cloud Function analyze_closed_trade
        update_data = {
            "status": "CLOSED",
            "exit_price": str(exit_price),
            "exit_reason": close_request.exit_reason,
            "closed_at": firestore.SERVER_TIMESTAMP,
            "closed_at_iso": datetime.now(timezone.utc).isoformat(),
            "final_pnl": final_pnl,  # Store final P&L
            "final_pnl_percent": pnl_percent,  # Store final P&L percent
        }
        
        with_firestore_retry(lambda: shadow_ref.update(update_data))
        
        logger.info(
            f"Shadow trade closed: {shadow_id} - {symbol} "
            f"exit @ ${exit_price}, P&L: ${final_pnl} ({pnl_percent}%)"
        )
        
        # Return updated trade data
        return {
            "id": shadow_id,
            "status": "CLOSED",
            "symbol": symbol,
            "entry_price": shadow_data.get("entry_price"),
            "exit_price": str(exit_price),
            "final_pnl": final_pnl,
            "final_pnl_percent": pnl_percent,
            "exit_reason": close_request.exit_reason,
            "message": "Trade closed successfully. AI analysis will be generated shortly.",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error closing shadow trade: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to close shadow trade: {e}")

