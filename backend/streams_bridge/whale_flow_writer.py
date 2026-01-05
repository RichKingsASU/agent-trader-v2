"""
Whale Flow Writer for Stream Bridge.

Integrates WhaleFlowService with the streams_bridge to write options flow
data to per-user whaleFlow collections while maintaining backward compatibility
with the global options_flow collection.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.services.whale_flow import WhaleFlowService

logger = logging.getLogger(__name__)


class WhaleFlowWriter:
    """
    Writer that ingests options flow to per-user whaleFlow collections.
    
    This writer sits alongside the FirestoreWriter and specifically handles
    whale flow ingestion using the WhaleFlowService.
    """
    
    def __init__(
        self,
        service: Optional[WhaleFlowService] = None,
        dry_run: bool = False,
    ):
        """
        Initialize the WhaleFlowWriter.
        
        Args:
            service: Optional WhaleFlowService instance
            dry_run: If True, log but don't write to Firestore
        """
        self.service = service or WhaleFlowService()
        self.dry_run = dry_run
    
    async def write_flow(
        self,
        uid: str,
        flow_data: Dict[str, Any],
        source: str = "stream_bridge"
    ) -> Optional[str]:
        """
        Write a single flow event for a user.
        
        Args:
            uid: User ID
            flow_data: Raw flow data
            source: Data source identifier
        
        Returns:
            Document ID or None if dry_run
        """
        if self.dry_run:
            logger.info(f"whale_flow_writer: dry_run write for user {uid}")
            return None
        
        try:
            doc_id = self.service.ingest_flow(uid, flow_data, source=source)
            return doc_id
        except Exception as e:
            logger.error(f"whale_flow_writer: Failed to write flow for user {uid}: {e}")
            return None
    
    async def write_flow_batch(
        self,
        uid: str,
        flows: List[Dict[str, Any]],
        source: str = "stream_bridge"
    ) -> List[str]:
        """
        Write multiple flow events for a user in a batch.
        
        Args:
            uid: User ID
            flows: List of raw flow data
            source: Data source identifier
        
        Returns:
            List of document IDs
        """
        if not flows:
            return []
        
        if self.dry_run:
            logger.info(f"whale_flow_writer: dry_run batch write for user {uid}, count={len(flows)}")
            return []
        
        try:
            doc_ids = self.service.ingest_batch(uid, flows, source=source)
            logger.info(f"whale_flow_writer: Batch wrote {len(doc_ids)} flows for user {uid}")
            return doc_ids
        except Exception as e:
            logger.error(f"whale_flow_writer: Failed to batch write flows for user {uid}: {e}")
            return []
    
    async def write_flow_multi_user(
        self,
        user_ids: List[str],
        flow_data: Dict[str, Any],
        source: str = "stream_bridge"
    ) -> Dict[str, Optional[str]]:
        """
        Write the same flow event to multiple users.
        
        Useful when broadcasting a flow to all subscribed users.
        
        Args:
            user_ids: List of user IDs
            flow_data: Raw flow data
            source: Data source identifier
        
        Returns:
            Dictionary mapping uid -> document ID
        """
        results = {}
        for uid in user_ids:
            doc_id = await self.write_flow(uid, flow_data, source=source)
            results[uid] = doc_id
        return results


# -------------------------------------------------------------------------
# Integration with OptionsFlowClient
# -------------------------------------------------------------------------

async def on_options_flow_event(
    flow_data: Dict[str, Any],
    whale_flow_writer: WhaleFlowWriter,
    user_ids: List[str],
) -> None:
    """
    Handle an incoming options flow event from the stream.
    
    This function can be called from OptionsFlowClient to write to both:
    1. Global options_flow collection (existing)
    2. Per-user whaleFlow collections (new)
    
    Args:
        flow_data: Raw flow data from provider
        whale_flow_writer: WhaleFlowWriter instance
        user_ids: List of user IDs to write flow to
    
    Example:
        >>> from backend.streams_bridge.whale_flow_writer import WhaleFlowWriter, on_options_flow_event
        >>> 
        >>> # In your OptionsFlowClient:
        >>> whale_writer = WhaleFlowWriter()
        >>> 
        >>> # When flow event arrives:
        >>> await on_options_flow_event(
        >>>     flow_data=parsed_flow,
        >>>     whale_flow_writer=whale_writer,
        >>>     user_ids=["user123", "user456"],
        >>> )
    """
    # Write to per-user whale flow collections
    await whale_flow_writer.write_flow_multi_user(
        user_ids=user_ids,
        flow_data=flow_data,
        source="options_stream"
    )


# -------------------------------------------------------------------------
# Example: Enhanced OptionsFlowClient
# -------------------------------------------------------------------------

class EnhancedOptionsFlowClient:
    """
    Example of how to enhance OptionsFlowClient to write to both collections.
    
    This is a reference implementation showing integration patterns.
    """
    
    def __init__(self, cfg, firestore_writer, whale_flow_writer, get_subscribed_users_fn):
        self.cfg = cfg
        self.firestore_writer = firestore_writer  # Original writer
        self.whale_flow_writer = whale_flow_writer  # New whale flow writer
        self.get_subscribed_users = get_subscribed_users_fn
    
    async def handle_flow_event(self, flow_data: Dict[str, Any]):
        """
        Handle incoming flow event - write to both collections.
        """
        # 1. Write to global options_flow collection (existing behavior)
        await self.firestore_writer.insert_options_flow([flow_data])
        
        # 2. Get subscribed users (e.g., premium tier users)
        subscribed_users = self.get_subscribed_users()
        
        # 3. Write to per-user whaleFlow collections (new behavior)
        if subscribed_users:
            await self.whale_flow_writer.write_flow_multi_user(
                user_ids=subscribed_users,
                flow_data=flow_data,
                source="options_stream"
            )
            
            logger.info(
                f"Wrote whale flow to {len(subscribed_users)} users: "
                f"{flow_data.get('underlying_symbol')}"
            )


# -------------------------------------------------------------------------
# Utility: Get subscribed users
# -------------------------------------------------------------------------

def get_subscribed_users_from_firestore(db) -> List[str]:
    """
    Get list of users subscribed to whale flow alerts.
    
    This is a placeholder - implement based on your user management system.
    
    Example implementation:
        - Query users collection for premium tier
        - Query subscriptions collection
        - Return list of user IDs
    
    Args:
        db: Firestore client
    
    Returns:
        List of user IDs
    """
    # TODO: Implement based on your subscription model
    # Example:
    # users = db.collection("users").where("tier", "==", "premium").stream()
    # return [user.id for user in users]
    
    return []  # Placeholder


# -------------------------------------------------------------------------
# Example: Webhook integration
# -------------------------------------------------------------------------

async def webhook_handler(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Example webhook handler for third-party flow providers.
    
    Args:
        request_data: Webhook payload from provider
    
    Returns:
        Response dictionary
    """
    try:
        # Parse provider-specific format
        flow_data = parse_provider_webhook(request_data)
        
        # Get subscribed users
        from backend.persistence.firebase_client import get_firestore_client
        db = get_firestore_client()
        user_ids = get_subscribed_users_from_firestore(db)
        
        # Write to whale flow
        whale_writer = WhaleFlowWriter()
        results = await whale_writer.write_flow_multi_user(
            user_ids=user_ids,
            flow_data=flow_data,
            source="webhook_provider"
        )
        
        return {
            "status": "success",
            "users_updated": len([r for r in results.values() if r]),
        }
    
    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


def parse_provider_webhook(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse provider-specific webhook format.
    
    Adapt this to your provider's format.
    """
    # Example: Map provider fields to our schema
    return {
        "timestamp": data.get("timestamp"),
        "underlying_symbol": data.get("symbol"),
        "option_symbol": data.get("contract"),
        "side": data.get("side"),
        "size": data.get("quantity"),
        "premium": data.get("total_premium"),
        "strike_price": data.get("strike"),
        "expiration_date": data.get("expiry"),
        "option_type": data.get("type"),
        "trade_price": data.get("price"),
        "bid_price": data.get("bid"),
        "ask_price": data.get("ask"),
        "spot_price": data.get("underlying_price"),
        "exchange": data.get("exchange"),
    }
