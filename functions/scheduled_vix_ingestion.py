"""
Scheduled VIX Ingestion Cloud Function.

This function runs every 5 minutes to fetch and store VIX (Volatility Index) data
for use by the VIX Guard circuit breaker.

Schedule: */5 * * * * (every 5 minutes during market hours)
"""

import logging
import os
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import firestore
from firebase_functions import scheduler_fn, options
import alpaca_trade_api as tradeapi

# Import VIX ingestion service from backend
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.risk.vix_ingestion import VIXIngestionService
from functions.utils.apca_env import get_apca_env

logger = logging.getLogger(__name__)


def _get_firestore() -> firestore.Client:
    """Get or initialize Firestore client."""
    if not firebase_admin._apps:
        from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod
        require_firestore_emulator_or_allow_prod(caller="functions.scheduled_vix_ingestion._get_firestore")
        firebase_admin.initialize_app()
    return firestore.client()


def _get_alpaca_client() -> tradeapi.REST:
    """
    Get Alpaca client using environment variables.
    
    Note: In production, these should be stored as Cloud Function secrets.
    """
    apca = get_apca_env()
    return tradeapi.REST(
        key_id=apca.api_key_id,
        secret_key=apca.api_secret_key,
        base_url=apca.api_base_url,
    )


@scheduler_fn.on_schedule(
    schedule="*/5 * * * *",  # Every 5 minutes
    timezone="America/New_York",
    secrets=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"],
    memory=options.MemoryOption.MB_256,
)
def ingest_vix_data(event: scheduler_fn.ScheduledEvent) -> None:
    """
    Scheduled function to ingest VIX data.
    
    This function:
    1. Fetches current VIX value from Alpaca (or Yahoo Finance as fallback)
    2. Stores the value in Firestore at systemStatus/vix_data
    3. Maintains a history collection for trend analysis
    
    Args:
        event: Scheduled event context
    """
    _ = event  # unused
    
    logger.info("Starting VIX ingestion...")
    
    try:
        # Initialize clients
        db = _get_firestore()
        alpaca = _get_alpaca_client()
        
        # Create VIX ingestion service
        vix_service = VIXIngestionService(db_client=db, alpaca_client=alpaca)
        
        # Fetch and store VIX
        # Note: We need to run this synchronously in Cloud Functions
        import asyncio
        vix_value = asyncio.run(vix_service.fetch_and_store_vix())
        
        if vix_value is None:
            logger.error("Failed to fetch VIX data")
            return
        
        logger.info(f"✅ Successfully ingested VIX data: {vix_value}")
        
        # Log to Firestore for monitoring
        db.collection("systemLogs").add({
            "type": "vix_ingestion",
            "timestamp": datetime.now(timezone.utc),
            "vix_value": vix_value,
            "status": "success",
        })
        
    except Exception as e:
        logger.error(f"Error in VIX ingestion: {e}", exc_info=True)
        
        # Log error to Firestore
        try:
            db = _get_firestore()
            db.collection("systemLogs").add({
                "type": "vix_ingestion",
                "timestamp": datetime.now(timezone.utc),
                "status": "error",
                "error": str(e),
            })
        except Exception as log_error:
            logger.error(f"Failed to log error to Firestore: {log_error}")


# HTTP endpoint for manual VIX refresh (useful for testing)
@scheduler_fn.on_schedule(
    schedule="0 9 * * 1-5",  # 9 AM ET, Monday-Friday (market open)
    timezone="America/New_York",
)
def initialize_daily_vix(event: scheduler_fn.ScheduledEvent) -> None:
    """
    Initialize VIX data at market open.
    
    This runs once at market open to ensure we have fresh VIX data
    before the first strategies run.
    """
    logger.info("Initializing daily VIX data at market open...")
    ingest_vix_data(event)
