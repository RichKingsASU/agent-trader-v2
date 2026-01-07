"""
WhaleFlowService: Ingestion and analysis service for institutional options flow data.

This service handles:
1. Mapping raw JSON from data providers to Firestore schema
2. Calculating conviction scores based on flow characteristics
3. Providing lookback queries for Maestro trade validation
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from google.cloud.firestore import Client

from backend.persistence.firebase_client import get_firestore_client
from backend.tenancy.paths import tenant_collection
from backend.time.nyse_time import parse_ts

logger = logging.getLogger(__name__)


class WhaleFlowService:
    """
    Service for ingesting and analyzing whale flow (unusual options activity).
    
    Stores data in Firestore at: users/{uid}/whaleFlow/{doc_id}
    """
    
    def __init__(self, db: Optional[Client] = None):
        """
        Initialize the WhaleFlowService.
        
        Args:
            db: Optional Firestore client. If not provided, creates one.
        """
        self.db = db or get_firestore_client()
    
    def map_flow_to_schema(
        self,
        uid: str,
        flow_data: Dict[str, Any],
        source: str = "provider"
    ) -> Dict[str, Any]:
        """
        Map incoming JSON from data provider to Firestore schema.
        
        Args:
            uid: User ID for scoping the data
            flow_data: Raw flow data from provider
            source: Data source identifier
        
        Returns:
            Dictionary ready for Firestore write
        
        Expected flow_data fields:
            - timestamp: ISO timestamp or datetime
            - underlying_symbol: Stock ticker
            - option_symbol: Full option contract symbol
            - side: "buy" or "sell"
            - size: Number of contracts
            - premium: Total premium (will be converted to Decimal)
            - strike_price: Strike price
            - expiration_date: Expiration date (YYYY-MM-DD)
            - option_type: "call" or "put"
            - trade_price: Price per contract
            - bid_price: Bid at time of trade
            - ask_price: Ask at time of trade
            - spot_price: Underlying spot price (optional)
            - implied_volatility: IV at time of trade (optional)
            - open_interest: OI at strike (optional)
            - volume: Option volume (optional)
            - flow_type: "SWEEP", "BLOCK", or detect automatically
            - exchange: Exchange identifier (optional)
        """
        # Parse timestamp
        timestamp = self._parse_timestamp(flow_data.get("timestamp"))
        
        # Extract core fields
        underlying_symbol = flow_data.get("underlying_symbol", "").upper()
        option_symbol = flow_data.get("option_symbol", "")
        side = flow_data.get("side", "unknown").lower()
        size = int(flow_data.get("size", 0))
        
        # Convert premium to Decimal with precision
        premium_raw = flow_data.get("premium") or flow_data.get("notional") or 0
        premium = Decimal(str(premium_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        # Parse prices
        strike_price = self._to_decimal(flow_data.get("strike_price"))
        trade_price = self._to_decimal(flow_data.get("trade_price"))
        bid_price = self._to_decimal(flow_data.get("bid_price"))
        ask_price = self._to_decimal(flow_data.get("ask_price"))
        spot_price = self._to_decimal(flow_data.get("spot_price"))
        
        # Parse option details
        option_type = flow_data.get("option_type", "").upper()
        expiration_date = flow_data.get("expiration_date", "")
        
        # Calculate additional metrics
        implied_volatility = flow_data.get("implied_volatility")
        open_interest = flow_data.get("open_interest", 0)
        volume = flow_data.get("volume", size)  # Default volume to size if not provided
        
        # Calculate vol/OI ratio
        vol_oi_ratio = self._calculate_vol_oi_ratio(volume, open_interest)
        
        # Determine if OTM
        is_otm = self._is_otm(option_type, strike_price, spot_price)
        
        # Detect flow type if not provided
        flow_type = flow_data.get("flow_type") or self._detect_flow_type(
            size, premium, trade_price, bid_price, ask_price
        )
        
        # Determine sentiment
        sentiment = self._determine_sentiment(option_type, side, trade_price, bid_price, ask_price)
        
        # Build the schema-compliant document
        document = {
            "timestamp": timestamp,
            "source": source,
            "underlying_symbol": underlying_symbol,
            "option_symbol": option_symbol,
            "flow_type": flow_type,
            "sentiment": sentiment,
            "side": side,
            "size": size,
            "premium": str(premium),  # Store as string for Firestore
            "strike_price": str(strike_price) if strike_price else None,
            "expiration_date": expiration_date,
            "option_type": option_type,
            "trade_price": str(trade_price) if trade_price else None,
            "bid_price": str(bid_price) if bid_price else None,
            "ask_price": str(ask_price) if ask_price else None,
            "spot_price": str(spot_price) if spot_price else None,
            "implied_volatility": str(implied_volatility) if implied_volatility else None,
            "open_interest": open_interest,
            "volume": volume,
            "vol_oi_ratio": str(vol_oi_ratio) if vol_oi_ratio else None,
            "is_otm": is_otm,
            "exchange": flow_data.get("exchange", ""),
            "conviction_score": None,  # Will be calculated next
            "raw_payload": flow_data.get("raw_payload", {}),
        }
        
        # Calculate conviction score
        document["conviction_score"] = str(self.calculate_conviction_score(document))
        
        return document
    
    def calculate_conviction_score(self, flow_data: Dict[str, Any]) -> Decimal:
        """
        Calculate a conviction score between 0 and 1 based on flow characteristics.
        
        Scoring algorithm:
        - Base 0.5 for BLOCK trades
        - Base 0.8 for SWEEP trades
        - Add +0.1 if isOTM is true
        - Add +0.1 if vol_oi_ratio > 1.2
        
        Args:
            flow_data: Flow document with required fields
        
        Returns:
            Decimal between 0 and 1 representing conviction level
        """
        flow_type = flow_data.get("flow_type", "").upper()
        is_otm = flow_data.get("is_otm", False)
        vol_oi_ratio_str = flow_data.get("vol_oi_ratio")
        
        # Base score based on flow type
        if flow_type == "SWEEP":
            score = Decimal("0.8")
        elif flow_type == "BLOCK":
            score = Decimal("0.5")
        else:
            # Unknown flow type gets neutral score
            score = Decimal("0.3")
        
        # Boost for OTM (suggests directional conviction)
        if is_otm:
            score += Decimal("0.1")
        
        # Boost for high vol/OI ratio (suggests new interest)
        if vol_oi_ratio_str:
            try:
                vol_oi_ratio = Decimal(vol_oi_ratio_str)
                if vol_oi_ratio > Decimal("1.2"):
                    score += Decimal("0.1")
            except (ValueError, TypeError):
                pass
        
        # Clamp to [0, 1]
        score = max(Decimal("0"), min(Decimal("1"), score))
        
        return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def ingest_flow(
        self,
        uid: str,
        flow_data: Dict[str, Any],
        source: str = "provider",
        doc_id: Optional[str] = None
    ) -> str:
        """
        Ingest a single flow event into Firestore.
        
        Args:
            uid: User ID
            flow_data: Raw flow data
            source: Data source identifier
            doc_id: Optional document ID. If not provided, Firestore auto-generates one.
        
        Returns:
            Document ID of the written flow
        """
        mapped_data = self.map_flow_to_schema(uid, flow_data, source)
        
        collection = self.db.collection("users").document(uid).collection("whaleFlow")
        
        if doc_id:
            doc_ref = collection.document(doc_id)
            doc_ref.set(mapped_data)
            logger.info(f"Ingested whale flow for user {uid}: {doc_id}")
            return doc_id
        else:
            _, doc_ref = collection.add(mapped_data)
            logger.info(f"Ingested whale flow for user {uid}: {doc_ref.id}")
            return doc_ref.id
    
    def ingest_batch(
        self,
        uid: str,
        flows: List[Dict[str, Any]],
        source: str = "provider"
    ) -> List[str]:
        """
        Ingest multiple flow events in a batch.
        
        Args:
            uid: User ID
            flows: List of raw flow data
            source: Data source identifier
        
        Returns:
            List of document IDs
        """
        collection = self.db.collection("users").document(uid).collection("whaleFlow")
        doc_ids = []
        
        batch = self.db.batch()
        for flow_data in flows:
            mapped_data = self.map_flow_to_schema(uid, flow_data, source)
            doc_ref = collection.document()  # Auto-generate ID
            batch.set(doc_ref, mapped_data)
            doc_ids.append(doc_ref.id)
        
        batch.commit()
        logger.info(f"Batch ingested {len(flows)} whale flows for user {uid}")
        return doc_ids
    
    def get_recent_conviction(
        self,
        uid: str,
        ticker: str,
        lookback_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Get recent conviction data for a ticker to help Maestro validate trades.
        
        This function retrieves whale flow activity for the specified ticker
        within the lookback window and provides aggregated conviction metrics.
        
        Args:
            uid: User ID
            ticker: Stock symbol to query
            lookback_minutes: How far back to look (default: 30 minutes)
        
        Returns:
            Dictionary with conviction metrics:
            {
                "ticker": str,
                "has_activity": bool,
                "total_flows": int,
                "avg_conviction": Decimal,
                "max_conviction": Decimal,
                "bullish_flows": int,
                "bearish_flows": int,
                "total_premium": Decimal,
                "dominant_sentiment": str,  # "BULLISH", "BEARISH", "NEUTRAL", or "MIXED"
                "flows": List[Dict],  # Recent flow documents
            }
        """
        ticker = ticker.upper()
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        
        # Query flows for this ticker within the lookback window
        collection = self.db.collection("users").document(uid).collection("whaleFlow")
        query = (
            collection
            .where("underlying_symbol", "==", ticker)
            .where("timestamp", ">=", cutoff_time)
            .order_by("timestamp", direction="DESCENDING")
            .limit(50)  # Reasonable limit
        )
        
        docs = query.stream()
        flows = [doc.to_dict() for doc in docs]
        
        if not flows:
            return {
                "ticker": ticker,
                "has_activity": False,
                "total_flows": 0,
                "avg_conviction": Decimal("0"),
                "max_conviction": Decimal("0"),
                "bullish_flows": 0,
                "bearish_flows": 0,
                "total_premium": Decimal("0"),
                "dominant_sentiment": "NEUTRAL",
                "flows": [],
            }
        
        # Calculate aggregated metrics
        conviction_scores = []
        bullish_count = 0
        bearish_count = 0
        total_premium = Decimal("0")
        
        for flow in flows:
            # Parse conviction score
            try:
                conviction = Decimal(flow.get("conviction_score", "0"))
                conviction_scores.append(conviction)
            except (ValueError, TypeError):
                pass
            
            # Count sentiment
            sentiment = flow.get("sentiment", "").upper()
            if sentiment == "BULLISH":
                bullish_count += 1
            elif sentiment == "BEARISH":
                bearish_count += 1
            
            # Sum premium
            try:
                premium = Decimal(flow.get("premium", "0"))
                total_premium += premium
            except (ValueError, TypeError):
                pass
        
        # Calculate conviction metrics
        avg_conviction = (
            sum(conviction_scores) / len(conviction_scores)
            if conviction_scores else Decimal("0")
        )
        max_conviction = max(conviction_scores) if conviction_scores else Decimal("0")
        
        # Determine dominant sentiment
        if bullish_count > bearish_count * 1.5:
            dominant_sentiment = "BULLISH"
        elif bearish_count > bullish_count * 1.5:
            dominant_sentiment = "BEARISH"
        elif abs(bullish_count - bearish_count) <= 1:
            dominant_sentiment = "NEUTRAL"
        else:
            dominant_sentiment = "MIXED"
        
        return {
            "ticker": ticker,
            "has_activity": True,
            "total_flows": len(flows),
            "avg_conviction": avg_conviction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "max_conviction": max_conviction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "bullish_flows": bullish_count,
            "bearish_flows": bearish_count,
            "total_premium": total_premium.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "dominant_sentiment": dominant_sentiment,
            "flows": flows,
        }
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def _parse_timestamp(self, timestamp: Any) -> datetime:
        """Parse various timestamp formats to datetime."""
        if timestamp is None:
            return datetime.now(timezone.utc)
        try:
            return parse_ts(timestamp)
        except Exception:
            return datetime.now(timezone.utc)
    
    def _to_decimal(self, value: Any) -> Optional[Decimal]:
        """Convert value to Decimal, handling None and various types."""
        if value is None:
            return None
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (ValueError, TypeError):
            return None
    
    def _calculate_vol_oi_ratio(self, volume: int, open_interest: int) -> Optional[Decimal]:
        """Calculate volume to open interest ratio."""
        if not open_interest or open_interest == 0:
            return None
        try:
            ratio = Decimal(str(volume)) / Decimal(str(open_interest))
            return ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (ValueError, TypeError, ZeroDivisionError):
            return None
    
    def _is_otm(
        self,
        option_type: str,
        strike_price: Optional[Decimal],
        spot_price: Optional[Decimal]
    ) -> bool:
        """Determine if option is out-of-the-money."""
        if not strike_price or not spot_price:
            return False
        
        option_type = option_type.upper()
        if option_type == "CALL":
            return strike_price > spot_price
        elif option_type == "PUT":
            return strike_price < spot_price
        
        return False
    
    def _detect_flow_type(
        self,
        size: int,
        premium: Decimal,
        trade_price: Optional[Decimal],
        bid_price: Optional[Decimal],
        ask_price: Optional[Decimal]
    ) -> str:
        """
        Detect flow type based on size and execution characteristics.
        
        SWEEP: Aggressive multi-exchange execution (usually at/above ask)
        BLOCK: Large single block trade (usually size > 100 contracts)
        """
        # SWEEP detection: trade at or above ask
        if trade_price and ask_price and trade_price >= ask_price:
            return "SWEEP"
        
        # BLOCK detection: large size
        if size >= 100:
            return "BLOCK"
        
        # Default
        return "UNKNOWN"
    
    def _determine_sentiment(
        self,
        option_type: str,
        side: str,
        trade_price: Optional[Decimal],
        bid_price: Optional[Decimal],
        ask_price: Optional[Decimal]
    ) -> str:
        """
        Determine sentiment based on option type, side, and execution.
        
        BULLISH: Calls bought aggressively (at/above ask) or puts sold
        BEARISH: Puts bought aggressively (at/above ask) or calls sold
        NEUTRAL: Other scenarios
        """
        option_type = option_type.upper()
        side = side.lower()
        
        # Check if executed at ask (aggressive)
        is_aggressive = (
            trade_price and ask_price and trade_price >= ask_price
        )
        
        if option_type == "CALL":
            if side == "buy" and is_aggressive:
                return "BULLISH"
            elif side == "sell":
                return "BEARISH"
        elif option_type == "PUT":
            if side == "buy" and is_aggressive:
                return "BEARISH"
            elif side == "sell":
                return "BULLISH"
        
        return "NEUTRAL"


# -------------------------------------------------------------------------
# Convenience Functions
# -------------------------------------------------------------------------

def get_whale_flow_service(db: Optional[Client] = None) -> WhaleFlowService:
    """Get a WhaleFlowService instance."""
    return WhaleFlowService(db=db)


def get_recent_conviction(
    uid: str,
    ticker: str,
    lookback_minutes: int = 30,
    db: Optional[Client] = None
) -> Dict[str, Any]:
    """
    Convenience function for Maestro to check recent whale activity.
    
    Args:
        uid: User ID
        ticker: Stock symbol
        lookback_minutes: Lookback window (default: 30 minutes)
        db: Optional Firestore client
    
    Returns:
        Conviction metrics dictionary
    
    Example:
        >>> from backend.services.whale_flow import get_recent_conviction
        >>> conviction = get_recent_conviction("user123", "AAPL", lookback_minutes=30)
        >>> if conviction["has_activity"] and conviction["avg_conviction"] > 0.7:
        >>>     print(f"Strong whale activity detected: {conviction['dominant_sentiment']}")
    """
    service = WhaleFlowService(db=db)
    return service.get_recent_conviction(uid, ticker, lookback_minutes)
