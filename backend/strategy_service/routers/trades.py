from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import requests
import os
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
import hashlib

from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.common.kill_switch import get_kill_switch_state
from backend.common.logging import log_event
from backend.observability.risk_signals import risk_correlation_id
from google.cloud import firestore
from google.api_core import exceptions as gexc

from ..db import build_raw_order, insert_paper_order
from ..db import insert_paper_order_idempotent
from ..models import PaperOrderCreate

router = APIRouter()
logger = logging.getLogger(__name__)

RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8002")

class TradeRequest(BaseModel):
    # Correlation across signal -> allocation -> execution
    correlation_id: str | None = None
    signal_id: str | None = None
    allocation_id: str | None = None
    execution_id: str | None = None
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: float = None
    idempotency_key: str | None = None


def _stable_id(*, scope: str, key: str) -> str:
    raw = f"{scope}|{key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:48]


def _resolve_idempotency_key(*, trade_request: TradeRequest, request: Request) -> str | None:
    for c in (
        trade_request.idempotency_key,
        request.headers.get("Idempotency-Key"),
        request.headers.get("X-Idempotency-Key"),
        request.headers.get("X-Request-Id"),
    ):
        if not c:
            continue
        s = str(c).strip()
        if s:
            return s
    return None


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


def create_shadow_trade(trade_request: TradeRequest, ctx: TenantContext, *, idempotency_key: str | None) -> dict:
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
        raw_key = idempotency_key
        shadow_id = _stable_id(scope="shadow_trade", key=raw_key) if raw_key else str(uuid4())
        
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
            "idempotency_key": raw_key,
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
        
        # Write to user-scoped shadowTradeHistory collection (idempotent on shadow_id).
        ref = (
            db.collection("users")
            .document(ctx.uid)
            .collection("shadowTradeHistory")
            .document(shadow_id)
        )
        try:
            with_firestore_retry(lambda: ref.create(shadow_trade))
        except gexc.AlreadyExists:
            snap = with_firestore_retry(lambda: ref.get())
            return snap.to_dict() if snap.exists else shadow_trade
        
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
    idem_key = _resolve_idempotency_key(trade_request=trade_request, request=request)
    stable_key = _stable_id(scope="trade_execute", key=idem_key) if idem_key else None
    
    # Check shadow mode flag (fail-safe: defaults to True)
    is_shadow_mode = get_shadow_mode_flag()
    logger.info(f"Executing trade in {'SHADOW' if is_shadow_mode else 'LIVE'} mode")

    try:
        log_event(
            logger,
            "execution.attempt",
            severity="INFO",
            correlation_id=corr,
            tenant_id=ctx.tenant_id,
            uid=ctx.uid,
            broker_account_id=str(trade_request.broker_account_id),
            strategy_id=str(trade_request.strategy_id),
            symbol=trade_request.symbol,
            side=trade_request.side,
            notional=float(trade_request.notional),
            instrument_type=trade_request.instrument_type,
            order_type=trade_request.order_type,
            time_in_force=trade_request.time_in_force,
            mode="shadow" if is_shadow_mode else "live",
            signal_id=trade_request.signal_id,
            allocation_id=trade_request.allocation_id,
            execution_id=execution_id,
        )
    except Exception:
        pass

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
        "correlation_id": corr,
        "signal_id": trade_request.signal_id,
        "allocation_id": trade_request.allocation_id,
        "execution_id": execution_id,
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
        try:
            log_event(
                logger,
                "execution.risk_check.denied",
                severity="WARNING",
                correlation_id=corr,
                tenant_id=ctx.tenant_id,
                uid=ctx.uid,
                signal_id=trade_request.signal_id,
                allocation_id=trade_request.allocation_id,
                execution_id=execution_id,
                scope=risk_result.get("scope"),
                reason=risk_result.get("reason"),
            )
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Trade not allowed by risk service: {risk_result.get('reason')}")
    else:
        try:
            log_event(
                logger,
                "execution.risk_check.allowed",
                severity="INFO",
                correlation_id=corr,
                tenant_id=ctx.tenant_id,
                uid=ctx.uid,
                signal_id=trade_request.signal_id,
                allocation_id=trade_request.allocation_id,
                execution_id=execution_id,
            )
        except Exception:
            pass

    # Capital reservation (best-effort, idempotent): prevents double-allocation on replay.
    # Reservation key is stable for a given idempotency key.
    if stable_key:
        try:
            db = get_firestore_client()
            res_ref = (
                db.collection("users")
                .document(ctx.uid)
                .collection("capital_reservations")
                .document(stable_key)
            )
            reservation = {
                "idempotency_key": idem_key,
                "scope": "trade_execute",
                "tenant_id": ctx.tenant_id,
                "uid": ctx.uid,
                "symbol": trade_request.symbol,
                "side": trade_request.side,
                "notional": str(trade_request.notional),
                "status": "reserved",
                "created_at": firestore.SERVER_TIMESTAMP,
                "created_at_iso": datetime.now(timezone.utc).isoformat(),
            }
            try:
                with_firestore_retry(lambda: res_ref.create(reservation))
            except gexc.AlreadyExists:
                # If reservation already exists, continue; downstream trade write is also idempotent.
                pass
        except Exception as e:
            logger.warning("capital_reservation_write_failed %s", e)

    # SHADOW MODE: Create synthetic order without contacting broker
    if is_shadow_mode:
        try:
            shadow_trade = create_shadow_trade(trade_request, ctx, idempotency_key=idem_key)
            logger.info(f"Shadow trade executed successfully: {shadow_trade['shadow_id']}")
            try:
                log_event(
                    logger,
                    "execution.completed",
                    severity="INFO",
                    correlation_id=corr,
                    tenant_id=ctx.tenant_id,
                    uid=ctx.uid,
                    mode="shadow",
                    signal_id=trade_request.signal_id,
                    allocation_id=trade_request.allocation_id,
                    execution_id=execution_id,
                    shadow_id=shadow_trade.get("shadow_id"),
                    symbol=trade_request.symbol,
                    side=trade_request.side,
                    quantity=shadow_trade.get("quantity"),
                    entry_price=shadow_trade.get("entry_price"),
                )
            except Exception:
                pass
            
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
                "correlation_id": corr,
                "signal_id": trade_request.signal_id,
                "allocation_id": trade_request.allocation_id,
                "execution_id": execution_id,
                "broker_account_id": str(trade_request.broker_account_id),
                "strategy_id": str(trade_request.strategy_id),
                "symbol": trade_request.symbol,
                "instrument_type": trade_request.instrument_type,
                "side": trade_request.side,
                "order_type": trade_request.order_type,
                "time_in_force": trade_request.time_in_force,
                "notional": trade_request.notional,
                "quantity": trade_request.quantity,
                "idempotency_key": idem_key,
            }
            payload = PaperOrderCreate(
                correlation_id=corr,
                signal_id=trade_request.signal_id,
                allocation_id=trade_request.allocation_id,
                execution_id=execution_id,
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
            
            if idem:
                result = insert_paper_order_idempotent(
                    tenant_id=ctx.tenant_id, payload=payload, idempotency_key=idem
                )
            else:
                result = insert_paper_order(tenant_id=ctx.tenant_id, payload=payload)
            logger.info(f"Live/Paper trade executed successfully: {result.id}")
            try:
                log_event(
                    logger,
                    "execution.completed",
                    severity="INFO",
                    correlation_id=corr,
                    tenant_id=ctx.tenant_id,
                    uid=ctx.uid,
                    mode="paper",
                    signal_id=trade_request.signal_id,
                    allocation_id=trade_request.allocation_id,
                    execution_id=execution_id,
                    paper_order_id=str(result.id),
                    symbol=trade_request.symbol,
                    side=trade_request.side,
                    notional=float(trade_request.notional),
                )
            except Exception:
                pass
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
        shadow_ref = (
            db.collection("users")
            .document(ctx.uid)
            .collection("shadowTradeHistory")
            .document(shadow_id)
        )
        shadow_doc = with_firestore_retry(lambda: shadow_ref.get())
        
        if not shadow_doc.exists:
            raise HTTPException(status_code=404, detail=f"Shadow trade {shadow_id} not found")
        
        shadow_data = shadow_doc.to_dict()
        
        # Verify ownership
        if shadow_data.get("uid") != ctx.uid:
            raise HTTPException(status_code=403, detail="Not authorized to close this trade")
        
        # Check if already closed
        if shadow_data.get("status") == "CLOSED":
            # Idempotent close: return existing closed trade.
            return {
                "id": shadow_id,
                "status": "CLOSED",
                "symbol": shadow_data.get("symbol"),
                "entry_price": shadow_data.get("entry_price"),
                "exit_price": shadow_data.get("exit_price"),
                "final_pnl": shadow_data.get("final_pnl", shadow_data.get("current_pnl", "0.00")),
                "final_pnl_percent": shadow_data.get("final_pnl_percent", shadow_data.get("pnl_percent", "0.00")),
                "exit_reason": shadow_data.get("exit_reason", close_request.exit_reason),
                "message": "Trade already closed (idempotent).",
            }
        
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

