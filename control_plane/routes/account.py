from fastapi import APIRouter, Depends, HTTPException
from control_plane.auth import require_auth
from control_plane.alpaca_client import get_trading_client
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import OrderSide, QueryOrderStatus

router = APIRouter()

@router.get("/account")
async def get_account_summary(user_email: str = Depends(require_auth)):
    """Fetch Alpaca account summary."""
    client = get_trading_client()
    if not client:
        raise HTTPException(status_code=500, detail="Alpaca client not initialized")
    
    try:
        account = client.get_account()
        return {
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "currency": account.currency,
            "status": account.status,
            "pattern_day_trader": account.pattern_day_trader,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trades")
async def get_recent_trades(user_email: str = Depends(require_auth)):
    """Fetch recent Alpaca orders."""
    client = get_trading_client()
    if not client:
        raise HTTPException(status_code=500, detail="Alpaca client not initialized")
    
    try:
        # Get last 5 orders
        filter = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=5,
            nested=True
        )
        orders = client.get_orders(filter)
        
        return [
            {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty) if order.qty else 0,
                "side": order.side,
                "type": order.type,
                "status": order.status,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "created_at": order.created_at.isoformat(),
            } for order in orders
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
