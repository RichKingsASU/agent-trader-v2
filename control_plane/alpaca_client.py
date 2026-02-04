import logging
from alpaca.trading.client import TradingClient
from control_plane.config import APCA_API_KEY_ID, APCA_API_SECRET_KEY, APCA_API_BASE_URL

logger = logging.getLogger(__name__)

def get_trading_client():
    """Initialize and return an Alpaca TradingClient."""
    if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
        logger.error("Alpaca keys missing - cannot initialize client")
        return None
    
    # Check if we are in paper mode based on URL
    is_paper = "paper" in APCA_API_BASE_URL.lower()
    
    return TradingClient(
        api_key=APCA_API_KEY_ID,
        secret_key=APCA_API_SECRET_KEY,
        paper=is_paper
    )
