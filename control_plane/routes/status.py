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
    
    Returns the current state of all safety-critical environment variables.
    This is READ-ONLY - never modifies the system.
    """
    logger.info(f"Status check by operator: {user_email}")
    
    status = get_system_status()
    
    return {
        **status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": user_email,
    }
