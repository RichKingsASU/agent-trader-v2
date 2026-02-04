"""
Status API routes.

GET /api/status - Read current system state
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request

from control_plane.auth import require_auth
from control_plane.config import get_system_status

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
async def get_status(request: Request, user_email: str = Depends(require_auth)):
    """
    Get current system status.
    
    Returns the current state of all safety-critical environment variables
    plus live market timing from Alpaca.
    """
    logger.info(f"Status check by operator: {user_email}")
    
    status = get_system_status()
    
    # Try to add market clock info
    market_clock = None
    from control_plane.alpaca_client import get_trading_client
    client = get_trading_client()
    if client:
        try:
            clock = client.get_clock()
            market_clock = {
                "is_open": clock.is_open,
                "next_open": clock.next_open.isoformat(),
                "next_close": clock.next_close.isoformat(),
                "timestamp": clock.timestamp.isoformat(),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch market clock: {e}")

    return {
        **status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": user_email,
        "market_clock": market_clock,
    }
