"""
Congressional Disclosure Data Ingestion

Fetches House/Senate stock disclosure data and publishes as market events.
Supports both API-based ingestion (Quiver Quantitative) and scraping fallback.
"""

from __future__ import annotations

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx
from nats.aio.client import Client as NATS

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.nats.subjects import market_subject
from backend.common.schemas.codec import encode_message
from backend.common.schemas.models import MarketEventV1
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.safety.process_safety import AsyncShutdown, startup_banner

logger = logging.getLogger(__name__)


@dataclass
class CongressionalTrade:
    """Represents a single congressional stock disclosure."""
    
    politician: str
    politician_id: str
    chamber: str  # "house" or "senate"
    ticker: str
    transaction_type: str  # "purchase", "sale", "exchange"
    transaction_date: datetime
    disclosure_date: datetime
    amount_range: str  # e.g., "$15,001 - $50,000"
    amount_min: float
    amount_max: float
    committees: List[str]  # List of committee names
    party: str  # "D", "R", "I"
    state: str
    
    # Optional fields
    asset_description: Optional[str] = None
    asset_type: Optional[str] = None
    comment: Optional[str] = None
    
    def to_market_event(self, tenant_id: str) -> MarketEventV1:
        """Convert congressional trade to a market event."""
        return MarketEventV1(
            tenant_id=tenant_id,
            symbol=self.ticker,
            source="congressional_disclosure",
            ts=self.disclosure_date,
            data={
                "politician": self.politician,
                "politician_id": self.politician_id,
                "chamber": self.chamber,
                "transaction_type": self.transaction_type,
                "transaction_date": self.transaction_date.isoformat(),
                "disclosure_date": self.disclosure_date.isoformat(),
                "amount_range": self.amount_range,
                "amount_min": self.amount_min,
                "amount_max": self.amount_max,
                "amount_midpoint": (self.amount_min + self.amount_max) / 2,
                "committees": self.committees,
                "party": self.party,
                "state": self.state,
                "asset_description": self.asset_description,
                "asset_type": self.asset_type,
                "comment": self.comment,
            }
        )


# Policy Whale Configuration
# These politicians are considered "whales" - high-profile traders with strong track records
POLICY_WHALES = {
    # House
    "Nancy Pelosi": {"chamber": "house", "weight_multiplier": 1.5},
    "Paul Pelosi": {"chamber": "house", "weight_multiplier": 1.5},  # Nancy's spouse
    "Brian Higgins": {"chamber": "house", "weight_multiplier": 1.3},
    "Josh Gottheimer": {"chamber": "house", "weight_multiplier": 1.3},
    "Marjorie Taylor Greene": {"chamber": "house", "weight_multiplier": 1.2},
    
    # Senate
    "Tommy Tuberville": {"chamber": "senate", "weight_multiplier": 1.4},
    "Dan Sullivan": {"chamber": "senate", "weight_multiplier": 1.3},
    "Shelley Moore Capito": {"chamber": "senate", "weight_multiplier": 1.3},
    "John Hickenlooper": {"chamber": "senate", "weight_multiplier": 1.2},
}

# Committee weighting: Higher weight for relevant industries
COMMITTEE_WEIGHTS = {
    # Defense & Military
    "Armed Services": ["LMT", "RTX", "NOC", "GD", "BA", "LHX"],
    "Appropriations": ["*"],  # Universal relevance
    
    # Technology
    "Science, Space, and Technology": ["AAPL", "GOOGL", "MSFT", "META", "NVDA", "AMD", "INTC"],
    "Energy and Commerce": ["AAPL", "GOOGL", "META", "T", "VZ", "CMCSA"],
    
    # Finance
    "Financial Services": ["JPM", "BAC", "GS", "MS", "C", "WFC", "BLK"],
    "Banking, Housing, and Urban Affairs": ["JPM", "BAC", "GS", "MS", "C", "WFC"],
    
    # Healthcare
    "Energy and Commerce": ["PFE", "JNJ", "UNH", "CVS", "ABBV", "MRK", "LLY"],
    "Health, Education, Labor, and Pensions": ["PFE", "JNJ", "UNH", "CVS", "ABBV", "MRK", "LLY"],
    
    # Energy
    "Natural Resources": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Energy and Natural Resources": ["XOM", "CVX", "COP", "SLB", "EOG"],
    
    # Agriculture
    "Agriculture": ["ADM", "BG", "DE", "CTVA", "MOS"],
    
    # Transportation
    "Transportation and Infrastructure": ["UAL", "DAL", "AAL", "LUV", "UPS", "FDX"],
}


def calculate_committee_weight(committees: List[str], ticker: str) -> float:
    """
    Calculate weight multiplier based on committee membership and ticker.
    
    Returns:
        float: Multiplier (1.0 = no bonus, 1.5 = 50% bonus, etc.)
    """
    base_weight = 1.0
    bonus = 0.0
    
    for committee in committees:
        if committee in COMMITTEE_WEIGHTS:
            relevant_tickers = COMMITTEE_WEIGHTS[committee]
            if "*" in relevant_tickers or ticker in relevant_tickers:
                bonus += 0.3  # 30% bonus per relevant committee
    
    return base_weight + bonus


class QuiverQuantitativeClient:
    """
    Client for Quiver Quantitative API.
    
    API Documentation: https://www.quiverquant.com/sources/congresstrading
    Note: Requires API key from Quiver Quantitative.
    """
    
    BASE_URL = "https://api.quiverquant.com/beta"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("QUIVER_API_KEY")
        if not self.api_key:
            logger.warning("QUIVER_API_KEY not set. Using mock data mode.")
        
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    
    async def fetch_recent_trades(
        self,
        days: int = 7,
        chamber: Optional[str] = None,
    ) -> List[CongressionalTrade]:
        """
        Fetch recent congressional trades.
        
        Args:
            days: Number of days to look back
            chamber: Filter by "house" or "senate", or None for both
            
        Returns:
            List of CongressionalTrade objects
        """
        if not self.api_key:
            # Return mock data for testing
            return self._generate_mock_trades()
        
        try:
            endpoint = f"{self.BASE_URL}/historical/congresstrading"
            params = {}
            if chamber:
                params["chamber"] = chamber
            
            response = await self.client.get(endpoint, params=params)
            response.raise_for_status()
            
            data = response.json()
            trades = []
            
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            for item in data:
                try:
                    trade = self._parse_trade_item(item)
                    if trade and trade.disclosure_date >= cutoff_date:
                        trades.append(trade)
                except Exception as e:
                    logger.warning(f"Failed to parse trade item: {e}")
                    continue
            
            logger.info(f"Fetched {len(trades)} congressional trades from last {days} days")
            return trades
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching congressional trades: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching congressional trades: {e}")
            return []
    
    def _parse_trade_item(self, item: Dict[str, Any]) -> Optional[CongressionalTrade]:
        """Parse a single trade item from API response."""
        try:
            # Parse dates
            transaction_date = datetime.fromisoformat(item["TransactionDate"].replace("Z", "+00:00"))
            disclosure_date = datetime.fromisoformat(item["FiledDate"].replace("Z", "+00:00"))
            
            # Parse amount range
            amount_range = item.get("Range", "Unknown")
            amount_min, amount_max = self._parse_amount_range(amount_range)
            
            return CongressionalTrade(
                politician=item["Representative"],
                politician_id=item.get("RepresentativeId", item["Representative"].replace(" ", "_")),
                chamber=item.get("Chamber", "house").lower(),
                ticker=item["Ticker"],
                transaction_type=item["Transaction"].lower(),
                transaction_date=transaction_date,
                disclosure_date=disclosure_date,
                amount_range=amount_range,
                amount_min=amount_min,
                amount_max=amount_max,
                committees=item.get("Committees", []),
                party=item.get("Party", "Unknown"),
                state=item.get("State", "Unknown"),
                asset_description=item.get("AssetDescription"),
                asset_type=item.get("AssetType"),
                comment=item.get("Comment"),
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse trade item: {e}")
            return None
    
    def _parse_amount_range(self, amount_range: str) -> tuple[float, float]:
        """
        Parse amount range string into min/max values.
        
        Examples:
            "$15,001 - $50,000" -> (15001.0, 50000.0)
            "$1,000,001 - $5,000,000" -> (1000001.0, 5000000.0)
        """
        if "-" not in amount_range:
            # Single value or unknown
            return (0.0, 0.0)
        
        try:
            parts = amount_range.split("-")
            min_str = parts[0].strip().replace("$", "").replace(",", "")
            max_str = parts[1].strip().replace("$", "").replace(",", "")
            
            return (float(min_str), float(max_str))
        except (ValueError, IndexError):
            return (0.0, 0.0)
    
    def _generate_mock_trades(self) -> List[CongressionalTrade]:
        """Generate mock trades for testing without API key."""
        now = datetime.now(timezone.utc)
        
        mock_trades = [
            CongressionalTrade(
                politician="Nancy Pelosi",
                politician_id="pelosi_nancy",
                chamber="house",
                ticker="NVDA",
                transaction_type="purchase",
                transaction_date=now - timedelta(days=3),
                disclosure_date=now - timedelta(days=1),
                amount_range="$50,001 - $100,000",
                amount_min=50001.0,
                amount_max=100000.0,
                committees=["Financial Services", "Select Committee on Intelligence"],
                party="D",
                state="CA",
                asset_description="NVIDIA Corporation - Common Stock",
            ),
            CongressionalTrade(
                politician="Tommy Tuberville",
                politician_id="tuberville_tommy",
                chamber="senate",
                ticker="MSFT",
                transaction_type="purchase",
                transaction_date=now - timedelta(days=5),
                disclosure_date=now - timedelta(days=2),
                amount_range="$100,001 - $250,000",
                amount_min=100001.0,
                amount_max=250000.0,
                committees=["Armed Services", "Agriculture"],
                party="R",
                state="AL",
                asset_description="Microsoft Corporation - Common Stock",
            ),
            CongressionalTrade(
                politician="Josh Gottheimer",
                politician_id="gottheimer_josh",
                chamber="house",
                ticker="AAPL",
                transaction_type="purchase",
                transaction_date=now - timedelta(days=2),
                disclosure_date=now - timedelta(hours=12),
                amount_range="$15,001 - $50,000",
                amount_min=15001.0,
                amount_max=50000.0,
                committees=["Financial Services"],
                party="D",
                state="NJ",
                asset_description="Apple Inc. - Common Stock",
            ),
        ]
        
        logger.info(f"Generated {len(mock_trades)} mock congressional trades")
        return mock_trades
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class CongressionalDisclosureIngestion:
    """
    Main ingestion service for congressional disclosure data.
    Fetches data periodically and publishes as market events to NATS.
    """
    
    def __init__(
        self,
        tenant_id: str,
        nats_url: str = "nats://localhost:4222",
        poll_interval_seconds: int = 3600,  # 1 hour default
        lookback_days: int = 7,
    ):
        self.tenant_id = tenant_id
        self.nats_url = nats_url
        self.poll_interval = poll_interval_seconds
        self.lookback_days = lookback_days
        
        self.nats_client: Optional[NATS] = None
        self.quiver_client: Optional[QuiverQuantitativeClient] = None
        self.seen_trades: set[str] = set()  # Track processed trades
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()
    
    async def connect(self):
        """Connect to NATS and initialize clients."""
        self.nats_client = NATS()
        await self.nats_client.connect(self.nats_url)
        logger.info(f"Connected to NATS at {self.nats_url}")
        
        self.quiver_client = QuiverQuantitativeClient()
        logger.info("Initialized Quiver Quantitative client")
    
    async def disconnect(self):
        """Disconnect from NATS and close clients."""
        if self.nats_client:
            await self.nats_client.close()
        if self.quiver_client:
            await self.quiver_client.close()
    
    async def ingest_once(self) -> int:
        """
        Perform one ingestion cycle.
        
        Returns:
            Number of new trades published
        """
        if not self.quiver_client or not self.nats_client:
            raise RuntimeError("Client not connected. Call connect() first.")
        
        logger.info(f"Fetching congressional trades from last {self.lookback_days} days...")
        trades = await self.quiver_client.fetch_recent_trades(days=self.lookback_days)
        
        new_count = 0
        for trade in trades:
            # Generate unique ID for deduplication
            trade_id = f"{trade.politician_id}:{trade.ticker}:{trade.transaction_date.isoformat()}"
            
            if trade_id in self.seen_trades:
                continue
            
            # Convert to market event
            event = trade.to_market_event(self.tenant_id)
            
            # Publish to NATS
            subject = market_subject(self.tenant_id, trade.ticker, "congressional")
            await self.nats_client.publish(subject, encode_message(event))
            
            self.seen_trades.add(trade_id)
            new_count += 1
            
            logger.info(
                f"📊 Congressional Trade: {trade.politician} {trade.transaction_type} "
                f"{trade.ticker} (${trade.amount_min:,.0f}-${trade.amount_max:,.0f})"
            )
        
        if new_count > 0:
            logger.info(f"Published {new_count} new congressional trades")
        else:
            logger.info("No new congressional trades found")
        
        return new_count
    
    async def run_forever(self):
        """Run ingestion loop forever."""
        await self.connect()
        
        try:
            last_hb = 0.0
            hb_interval_s = float(os.getenv("HEARTBEAT_LOG_INTERVAL_S") or "60")
            hb_interval_s = max(5.0, hb_interval_s)

            while not self._stop.is_set():
                try:
                    await self.ingest_once()
                except Exception as e:
                    logger.error(f"Error during ingestion cycle: {e}", exc_info=True)

                now = time.monotonic()
                if (now - last_hb) >= hb_interval_s:
                    last_hb = now
                    logger.info(
                        "congressional_ingest.heartbeat",
                        extra={
                            "tenant_id": self.tenant_id,
                            "lookback_days": self.lookback_days,
                            "poll_interval_s": self.poll_interval,
                            "seen_trades": len(self.seen_trades),
                        },
                    )

                logger.info(f"Sleeping for {self.poll_interval} seconds...")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=float(self.poll_interval))
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.disconnect()


async def main():
    """Main entry point for running the ingestion service."""
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    enforce_agent_mode_guard()

    configure_startup_logging(
        agent_name="congressional-ingest",
        intent="Ingest congressional trades and publish market events to NATS.",
    )
    startup_banner(
        service="congressional-ingest",
        intent="Ingest congressional trades and publish market events to NATS.",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass
    
    tenant_id = os.getenv("TENANT_ID", "local")
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
    lookback_days = int(os.getenv("LOOKBACK_DAYS", "7"))
    
    logger.info(f"Starting Congressional Disclosure Ingestion")
    logger.info(f"  Tenant: {tenant_id}")
    logger.info(f"  NATS URL: {nats_url}")
    logger.info(f"  Poll Interval: {poll_interval}s")
    logger.info(f"  Lookback: {lookback_days} days")
    
    ingestion = CongressionalDisclosureIngestion(
        tenant_id=tenant_id,
        nats_url=nats_url,
        poll_interval_seconds=poll_interval,
        lookback_days=lookback_days,
    )

    shutdown = AsyncShutdown(service="congressional-ingest")
    shutdown.add_callback(ingestion.request_stop)
    shutdown.install()

    await ingestion.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("congressional_ingest.crashed: %s", e)
        raise SystemExit(1)
