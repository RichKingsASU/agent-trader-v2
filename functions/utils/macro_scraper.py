"""
Macro-Event Scraper for Economic Calendar and News Analysis

This module provides functionality to:
1. Scrape Federal Reserve Economic Calendar and major economic releases
2. Fetch top-tier news via Alpaca News API
3. Analyze economic surprises using Gemini AI
4. Update systemStatus/market_regime to 'Volatility_Event' when significant surprises detected
5. Notify strategies to widen stop-losses during macro volatility events

Major Economic Events Tracked:
- CPI (Consumer Price Index)
- FOMC (Federal Reserve Interest Rate Decisions)
- Non-Farm Payrolls / Jobs Report
- GDP
- PCE (Personal Consumption Expenditures)
- Retail Sales
- Unemployment Rate
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum

import requests
from google.cloud import firestore
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest

logger = logging.getLogger(__name__)


class EventSeverity(Enum):
    """Classification of macro event significance"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MarketRegimeStatus(Enum):
    """Market regime status values"""
    NORMAL = "Normal"
    VOLATILITY_EVENT = "Volatility_Event"
    HIGH_VOLATILITY = "High_Volatility"
    EXTREME_VOLATILITY = "Extreme_Volatility"


@dataclass
class EconomicRelease:
    """Economic data release information"""
    event_name: str
    release_time: datetime
    actual_value: Optional[float] = None
    expected_value: Optional[float] = None
    previous_value: Optional[float] = None
    surprise_magnitude: Optional[float] = None  # Percentage difference from expected
    severity: EventSeverity = EventSeverity.MEDIUM
    source: str = "federal_reserve"
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class NewsAlert:
    """High-priority news alert"""
    headline: str
    source: str
    timestamp: datetime
    symbols: List[str]
    url: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class MacroAnalysis:
    """AI analysis of macro event significance"""
    event_name: str
    is_significant_surprise: bool
    surprise_magnitude: float
    market_impact: str  # "bullish", "bearish", "neutral"
    volatility_expectation: str  # "low", "medium", "high", "extreme"
    recommended_action: str
    confidence_score: float
    reasoning: str
    timestamp: datetime


# Major economic indicators to monitor
MAJOR_ECONOMIC_EVENTS = {
    "CPI": {
        "full_name": "Consumer Price Index",
        "keywords": ["cpi", "consumer price", "inflation"],
        "surprise_threshold": 0.2,  # 0.2% deviation triggers alert
        "severity": EventSeverity.HIGH
    },
    "FOMC": {
        "full_name": "Federal Reserve Interest Rate Decision",
        "keywords": ["fomc", "federal reserve", "interest rate", "fed decision"],
        "surprise_threshold": 0.25,  # 25 bps
        "severity": EventSeverity.CRITICAL
    },
    "NFP": {
        "full_name": "Non-Farm Payrolls",
        "keywords": ["non-farm payroll", "nfp", "jobs report", "employment"],
        "surprise_threshold": 50000,  # 50k jobs difference
        "severity": EventSeverity.HIGH
    },
    "GDP": {
        "full_name": "Gross Domestic Product",
        "keywords": ["gdp", "gross domestic"],
        "surprise_threshold": 0.5,  # 0.5% difference
        "severity": EventSeverity.HIGH
    },
    "PCE": {
        "full_name": "Personal Consumption Expenditures",
        "keywords": ["pce", "personal consumption"],
        "surprise_threshold": 0.2,
        "severity": EventSeverity.MEDIUM
    },
    "UNEMPLOYMENT": {
        "full_name": "Unemployment Rate",
        "keywords": ["unemployment rate", "jobless"],
        "surprise_threshold": 0.2,  # 0.2% difference
        "severity": EventSeverity.HIGH
    }
}


class FedEconomicCalendarScraper:
    """
    Scraper for Federal Reserve Economic Calendar and major economic releases.
    
    Data sources:
    1. Federal Reserve Economic Data (FRED) API
    2. Bureau of Labor Statistics
    3. Bureau of Economic Analysis
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AgentTrader MacroScraper/1.0"
        })
    
    def fetch_recent_releases(self, lookback_days: int = 7) -> List[EconomicRelease]:
        """
        Fetch recent economic data releases.
        
        Args:
            lookback_days: Number of days to look back for releases
            
        Returns:
            List of EconomicRelease objects
        """
        releases = []
        
        # Try multiple sources
        releases.extend(self._fetch_from_fred(lookback_days))
        releases.extend(self._fetch_from_bls(lookback_days))
        
        return releases
    
    def _fetch_from_fred(self, lookback_days: int) -> List[EconomicRelease]:
        """
        Fetch data from Federal Reserve Economic Data (FRED).
        
        Note: This requires FRED API key. If not available, returns empty list.
        """
        import os
        
        fred_api_key = os.getenv("FRED_API_KEY")
        if not fred_api_key:
            logger.warning("FRED_API_KEY not set. Skipping FRED data fetch.")
            return []
        
        releases = []
        base_url = "https://api.stlouisfed.org/fred/series/observations"
        
        # Map of FRED series IDs to our event names
        series_map = {
            "CPIAUCSL": "CPI",
            "UNRATE": "UNEMPLOYMENT",
            "PAYEMS": "NFP",
            "GDP": "GDP",
            "PCEPI": "PCE"
        }
        
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=lookback_days)
        
        for series_id, event_name in series_map.items():
            try:
                params = {
                    "series_id": series_id,
                    "api_key": fred_api_key,
                    "file_type": "json",
                    "observation_start": start_date.strftime("%Y-%m-%d"),
                    "observation_end": end_date.strftime("%Y-%m-%d"),
                    "sort_order": "desc",
                    "limit": 5
                }
                
                response = self.session.get(base_url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                observations = data.get("observations", [])
                
                for obs in observations:
                    value = obs.get("value")
                    if value and value != ".":
                        release = EconomicRelease(
                            event_name=event_name,
                            release_time=datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                            actual_value=float(value),
                            source="FRED",
                            raw_data=obs
                        )
                        releases.append(release)
                
                logger.info(f"Fetched {len(observations)} observations for {event_name} from FRED")
                
            except Exception as e:
                logger.warning(f"Failed to fetch {series_id} from FRED: {e}")
                continue
        
        return releases
    
    def _fetch_from_bls(self, lookback_days: int) -> List[EconomicRelease]:
        """
        Fetch data from Bureau of Labor Statistics.
        
        This is a placeholder for BLS API integration.
        """
        # BLS API requires registration and specific series IDs
        # For now, we'll rely on FRED and news parsing
        logger.debug("BLS integration not yet implemented")
        return []


class AlpacaMacroNewsFetcher:
    """
    Fetches macro-economic news from Alpaca News API.
    
    Filters for high-impact economic news and events.
    """
    
    def __init__(self, api_key: str, secret_key: str):
        self.news_client = NewsClient(api_key=api_key, secret_key=secret_key)
    
    def fetch_macro_news(self, lookback_hours: int = 24, limit: int = 100) -> List[NewsAlert]:
        """
        Fetch recent macro-economic news.
        
        Args:
            lookback_hours: Hours to look back
            limit: Maximum number of articles
            
        Returns:
            List of NewsAlert objects filtered for macro significance
        """
        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=lookback_hours)
            
            logger.info(f"Fetching macro news from {start_time} to {end_time}")
            
            # Search for macro-economic keywords
            # Alpaca News API doesn't support keyword search in free tier,
            # so we fetch general news and filter
            news_request = NewsRequest(
                start=start_time,
                end=end_time,
                limit=limit,
                sort="desc"
            )
            
            news_set = self.news_client.get_news(news_request)
            
            # Filter for macro-relevant news
            macro_news = []
            for article in news_set.data.values():
                if self._is_macro_relevant(article.headline):
                    alert = NewsAlert(
                        headline=article.headline,
                        source=article.source if hasattr(article, 'source') else "Alpaca",
                        timestamp=article.created_at if hasattr(article, 'created_at') else datetime.now(timezone.utc),
                        symbols=article.symbols if hasattr(article, 'symbols') else [],
                        url=article.url if hasattr(article, 'url') else None,
                        summary=article.summary if hasattr(article, 'summary') else None
                    )
                    macro_news.append(alert)
            
            logger.info(f"Filtered {len(macro_news)} macro-relevant articles from {len(news_set.data)} total")
            return macro_news
            
        except Exception as e:
            logger.exception(f"Failed to fetch macro news from Alpaca: {e}")
            return []
    
    def _is_macro_relevant(self, headline: str) -> bool:
        """
        Determine if a headline is macro-economically relevant.
        
        Args:
            headline: News headline
            
        Returns:
            True if headline contains macro keywords
        """
        headline_lower = headline.lower()
        
        # Check against all major economic event keywords
        for event_config in MAJOR_ECONOMIC_EVENTS.values():
            for keyword in event_config["keywords"]:
                if keyword in headline_lower:
                    return True
        
        # Additional macro keywords
        macro_keywords = [
            "federal reserve", "fed", "fomc", "interest rate", "rate cut", "rate hike",
            "inflation", "cpi", "pce", "unemployment", "jobs report", "nfp",
            "gdp", "recession", "economy", "economic", "treasury",
            "powell", "yellen", "fed chair", "central bank",
            "fiscal policy", "monetary policy", "quantitative easing", "qe",
            "dollar", "treasury yield", "bond market"
        ]
        
        return any(keyword in headline_lower for keyword in macro_keywords)


class GeminiMacroAnalyzer:
    """
    Uses Gemini AI to analyze economic data and news for market impact.
    """
    
    def __init__(self, project_id: str, location: str = "us-central1", model_id: str = "gemini-2.5-flash"):
        self.project_id = project_id
        self.location = location
        self.model_id = model_id
        self._initialized = False
    
    def _init_vertex_ai(self):
        """Initialize Vertex AI if not already done"""
        if not self._initialized:
            try:
                import vertexai
                vertexai.init(project=self.project_id, location=self.location)
                self._initialized = True
                logger.info(f"Initialized Vertex AI with project={self.project_id}, location={self.location}")
            except Exception as e:
                logger.error(f"Failed to initialize Vertex AI: {e}")
                raise
    
    def analyze_economic_release(
        self,
        release: EconomicRelease,
        news_context: List[NewsAlert] = None
    ) -> Optional[MacroAnalysis]:
        """
        Analyze an economic release for market impact using Gemini.
        
        Args:
            release: Economic release data
            news_context: Optional related news for context
            
        Returns:
            MacroAnalysis object with AI assessment
        """
        self._init_vertex_ai()
        
        try:
            from vertexai.generative_models import GenerativeModel
            
            model = GenerativeModel(self.model_id)
            
            # Build analysis prompt
            prompt = self._build_analysis_prompt(release, news_context)
            
            logger.info(f"Analyzing {release.event_name} with Gemini {self.model_id}")
            
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2,  # Low temperature for factual analysis
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 1024,
                }
            )
            
            response_text = response.text.strip()
            logger.debug(f"Gemini response: {response_text}")
            
            # Parse response
            analysis = self._parse_analysis_response(response_text, release)
            return analysis
            
        except Exception as e:
            logger.exception(f"Failed to analyze release with Gemini: {e}")
            return None
    
    def _build_analysis_prompt(
        self,
        release: EconomicRelease,
        news_context: List[NewsAlert] = None
    ) -> str:
        """Build prompt for Gemini analysis"""
        
        event_config = MAJOR_ECONOMIC_EVENTS.get(release.event_name, {})
        surprise_threshold = event_config.get("surprise_threshold", 0)
        
        prompt = f"""You are a macro-economic analyst for a trading system. Analyze this economic release:

EVENT: {release.event_name} ({event_config.get('full_name', release.event_name)})
RELEASE TIME: {release.release_time.isoformat()}
ACTUAL VALUE: {release.actual_value}
EXPECTED VALUE: {release.expected_value}
PREVIOUS VALUE: {release.previous_value}
"""
        
        if release.surprise_magnitude is not None:
            prompt += f"SURPRISE MAGNITUDE: {release.surprise_magnitude:.2f}%\n"
        
        prompt += f"\nSURPRISE THRESHOLD: {surprise_threshold} (values exceeding this are considered significant)\n"
        
        if news_context:
            prompt += f"\n\nRELATED NEWS HEADLINES:\n"
            for i, news in enumerate(news_context[:5], 1):
                prompt += f"{i}. {news.headline} ({news.source})\n"
        
        prompt += """

TASK: Analyze this release and provide:
1. Is this a SIGNIFICANT SURPRISE that will cause market volatility? (yes/no)
2. Surprise magnitude as percentage difference from expected
3. Market impact direction (bullish/bearish/neutral)
4. Expected volatility level (low/medium/high/extreme)
5. Recommended action for trading strategies
6. Confidence score (0.0 to 1.0)
7. Brief reasoning (2-3 sentences)

Respond in this EXACT JSON format:
{
    "is_significant_surprise": true/false,
    "surprise_magnitude": 0.0,
    "market_impact": "bullish/bearish/neutral",
    "volatility_expectation": "low/medium/high/extreme",
    "recommended_action": "widen_stops/tighten_stops/reduce_size/pause_trading/normal",
    "confidence_score": 0.0,
    "reasoning": "Your analysis here"
}
"""
        
        return prompt
    
    def _parse_analysis_response(self, response_text: str, release: EconomicRelease) -> MacroAnalysis:
        """Parse Gemini response into MacroAnalysis object"""
        import json
        
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        
        data = json.loads(response_text)
        
        return MacroAnalysis(
            event_name=release.event_name,
            is_significant_surprise=bool(data["is_significant_surprise"]),
            surprise_magnitude=float(data["surprise_magnitude"]),
            market_impact=str(data["market_impact"]),
            volatility_expectation=str(data["volatility_expectation"]),
            recommended_action=str(data["recommended_action"]),
            confidence_score=float(data["confidence_score"]),
            reasoning=str(data["reasoning"]),
            timestamp=datetime.now(timezone.utc)
        )


class MacroEventCoordinator:
    """
    Coordinates macro event detection and strategy response.
    
    Main orchestrator that:
    1. Scrapes economic calendar
    2. Fetches relevant news
    3. Analyzes with Gemini
    4. Updates market regime in Firestore
    5. Notifies strategies
    """
    
    def __init__(
        self,
        db_client: firestore.Client,
        alpaca_api_key: str,
        alpaca_secret_key: str,
        vertex_project_id: str,
        vertex_location: str = "us-central1",
        vertex_model_id: str = "gemini-2.5-flash"
    ):
        self.db = db_client
        self.fed_scraper = FedEconomicCalendarScraper()
        self.news_fetcher = AlpacaMacroNewsFetcher(alpaca_api_key, alpaca_secret_key)
        self.analyzer = GeminiMacroAnalyzer(vertex_project_id, vertex_location, vertex_model_id)
    
    def scan_and_analyze(self, lookback_hours: int = 24) -> Dict[str, Any]:
        """
        Scan for macro events and analyze their impact.
        
        Args:
            lookback_hours: Hours to look back for events
            
        Returns:
            Summary of findings and actions taken
        """
        logger.info(f"Starting macro event scan (lookback={lookback_hours}h)")
        
        results = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "lookback_hours": lookback_hours,
            "releases_found": 0,
            "news_articles": 0,
            "significant_events": [],
            "market_regime_updated": False,
            "errors": []
        }
        
        try:
            # Step 1: Fetch economic releases
            lookback_days = max(1, lookback_hours // 24)
            releases = self.fed_scraper.fetch_recent_releases(lookback_days)
            results["releases_found"] = len(releases)
            
            logger.info(f"Found {len(releases)} economic releases")
            
            # Step 2: Fetch macro news
            news = self.news_fetcher.fetch_macro_news(lookback_hours)
            results["news_articles"] = len(news)
            
            logger.info(f"Found {len(news)} macro-relevant news articles")
            
            # Step 3: Analyze each release with Gemini
            significant_events = []
            
            for release in releases:
                # Calculate surprise magnitude if we have expected value
                if release.expected_value and release.actual_value:
                    if release.expected_value != 0:
                        surprise_pct = ((release.actual_value - release.expected_value) / abs(release.expected_value)) * 100
                        release.surprise_magnitude = surprise_pct
                    else:
                        release.surprise_magnitude = 0.0
                
                # Get related news for context
                related_news = self._find_related_news(release, news)
                
                # Analyze with Gemini
                analysis = self.analyzer.analyze_economic_release(release, related_news)
                
                if analysis and analysis.is_significant_surprise:
                    significant_events.append({
                        "release": asdict(release),
                        "analysis": asdict(analysis),
                        "related_news_count": len(related_news)
                    })
                    
                    logger.warning(
                        f"SIGNIFICANT SURPRISE DETECTED: {release.event_name} - "
                        f"Magnitude: {analysis.surprise_magnitude:.2f}%, "
                        f"Volatility: {analysis.volatility_expectation}, "
                        f"Action: {analysis.recommended_action}"
                    )
            
            results["significant_events"] = significant_events
            
            # Step 4: Update market regime if needed
            if significant_events:
                regime_status = self._determine_regime_status(significant_events)
                self._update_market_regime(regime_status, significant_events)
                results["market_regime_updated"] = True
                results["new_regime"] = regime_status.value
            
            logger.info(f"Macro scan complete. Found {len(significant_events)} significant events.")
            
        except Exception as e:
            logger.exception("Error during macro event scan")
            results["errors"].append(str(e))
        
        return results
    
    def _find_related_news(self, release: EconomicRelease, all_news: List[NewsAlert]) -> List[NewsAlert]:
        """Find news articles related to an economic release"""
        related = []
        event_config = MAJOR_ECONOMIC_EVENTS.get(release.event_name, {})
        keywords = event_config.get("keywords", [])
        
        for news in all_news:
            headline_lower = news.headline.lower()
            if any(keyword in headline_lower for keyword in keywords):
                related.append(news)
        
        return related
    
    def _determine_regime_status(self, significant_events: List[Dict]) -> MarketRegimeStatus:
        """
        Determine appropriate market regime status based on significant events.
        
        Args:
            significant_events: List of significant events with analyses
            
        Returns:
            MarketRegimeStatus enum value
        """
        if not significant_events:
            return MarketRegimeStatus.NORMAL
        
        # Count events by volatility expectation
        extreme_count = sum(1 for e in significant_events 
                          if e["analysis"]["volatility_expectation"] == "extreme")
        high_count = sum(1 for e in significant_events 
                       if e["analysis"]["volatility_expectation"] == "high")
        
        # Determine regime
        if extreme_count >= 1:
            return MarketRegimeStatus.EXTREME_VOLATILITY
        elif high_count >= 2:
            return MarketRegimeStatus.HIGH_VOLATILITY
        elif high_count >= 1 or len(significant_events) >= 2:
            return MarketRegimeStatus.VOLATILITY_EVENT
        else:
            return MarketRegimeStatus.VOLATILITY_EVENT  # Default for any significant event
    
    def _update_market_regime(self, status: MarketRegimeStatus, events: List[Dict]):
        """
        Update systemStatus/market_regime in Firestore.
        
        Args:
            status: New market regime status
            events: List of significant events that triggered the update
        """
        try:
            regime_ref = self.db.collection("systemStatus").document("market_regime")
            
            # Read current regime data
            current_regime = regime_ref.get()
            regime_data = current_regime.to_dict() if current_regime.exists else {}
            
            # Update with macro event status
            regime_data.update({
                "macro_event_status": status.value,
                "macro_event_detected": True,
                "macro_event_time": firestore.SERVER_TIMESTAMP,
                "macro_events": [
                    {
                        "event_name": e["release"]["event_name"],
                        "surprise_magnitude": e["analysis"]["surprise_magnitude"],
                        "volatility_expectation": e["analysis"]["volatility_expectation"],
                        "recommended_action": e["analysis"]["recommended_action"],
                        "confidence": e["analysis"]["confidence_score"],
                        "reasoning": e["analysis"]["reasoning"]
                    }
                    for e in events
                ],
                "stop_loss_multiplier": self._calculate_stop_loss_multiplier(status),
                "position_size_multiplier": self._calculate_position_size_multiplier(status),
                "updated_by": "macro_scraper",
                "last_updated": firestore.SERVER_TIMESTAMP
            })
            
            # Write to Firestore
            regime_ref.set(regime_data, merge=True)
            
            logger.warning(
                f"MARKET REGIME UPDATED: {status.value} - "
                f"Stop-loss multiplier: {regime_data['stop_loss_multiplier']:.2f}x, "
                f"Position size multiplier: {regime_data['position_size_multiplier']:.2f}x"
            )
            
            # Also write to a dedicated macro_events subcollection for history
            self._archive_event(events)
            
        except Exception as e:
            logger.exception("Failed to update market regime in Firestore")
            raise
    
    def _calculate_stop_loss_multiplier(self, status: MarketRegimeStatus) -> float:
        """
        Calculate stop-loss width multiplier based on regime.
        
        Returns:
            Multiplier to apply to normal stop-losses (1.0 = normal, >1.0 = wider)
        """
        multipliers = {
            MarketRegimeStatus.NORMAL: 1.0,
            MarketRegimeStatus.VOLATILITY_EVENT: 1.5,
            MarketRegimeStatus.HIGH_VOLATILITY: 2.0,
            MarketRegimeStatus.EXTREME_VOLATILITY: 2.5
        }
        return multipliers.get(status, 1.5)
    
    def _calculate_position_size_multiplier(self, status: MarketRegimeStatus) -> float:
        """
        Calculate position size multiplier based on regime.
        
        Returns:
            Multiplier to apply to normal position sizes (1.0 = normal, <1.0 = smaller)
        """
        multipliers = {
            MarketRegimeStatus.NORMAL: 1.0,
            MarketRegimeStatus.VOLATILITY_EVENT: 0.75,
            MarketRegimeStatus.HIGH_VOLATILITY: 0.50,
            MarketRegimeStatus.EXTREME_VOLATILITY: 0.25
        }
        return multipliers.get(status, 0.75)
    
    def _archive_event(self, events: List[Dict]):
        """Archive significant events to Firestore for historical analysis"""
        try:
            for event_data in events:
                doc_ref = self.db.collection("systemStatus").document("market_regime").collection("macro_events").document()
                doc_ref.set({
                    **event_data,
                    "archived_at": firestore.SERVER_TIMESTAMP
                })
        except Exception as e:
            logger.warning(f"Failed to archive macro events: {e}")
    
    def clear_volatility_event(self, reason: str = "Manual clear"):
        """
        Clear volatility event status and return to normal regime.
        
        Args:
            reason: Reason for clearing the event
        """
        try:
            regime_ref = self.db.collection("systemStatus").document("market_regime")
            regime_ref.set({
                "macro_event_status": MarketRegimeStatus.NORMAL.value,
                "macro_event_detected": False,
                "macro_events": [],
                "stop_loss_multiplier": 1.0,
                "position_size_multiplier": 1.0,
                "cleared_at": firestore.SERVER_TIMESTAMP,
                "cleared_reason": reason,
                "updated_by": "macro_scraper",
                "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
            
            logger.info(f"Cleared volatility event status: {reason}")
            
        except Exception as e:
            logger.exception("Failed to clear volatility event")
            raise


def create_macro_coordinator(
    db_client: firestore.Client = None,
    alpaca_api_key: str = None,
    alpaca_secret_key: str = None,
    vertex_project_id: str = None
) -> MacroEventCoordinator:
    """
    Factory function to create MacroEventCoordinator with environment defaults.
    
    Args:
        db_client: Firestore client (creates new if None)
        alpaca_api_key: Alpaca API key (reads from env if None)
        alpaca_secret_key: Alpaca secret key (reads from env if None)
        vertex_project_id: Vertex AI project ID (reads from env if None)
        
    Returns:
        Configured MacroEventCoordinator instance
    """
    import os
    from backend.common.env import (
        get_alpaca_api_key,
        get_alpaca_secret_key,
        get_vertex_ai_project_id,
        get_vertex_ai_location,
        get_vertex_ai_model_id
    )
    
    # Create Firestore client if not provided
    if db_client is None:
        db_client = firestore.Client()
    
    # Get credentials from environment if not provided
    alpaca_key = alpaca_api_key or get_alpaca_api_key(required=True)
    alpaca_secret = alpaca_secret_key or get_alpaca_secret_key(required=True)
    vertex_project = vertex_project_id or get_vertex_ai_project_id(required=True)
    vertex_location = get_vertex_ai_location()
    vertex_model = get_vertex_ai_model_id()
    
    return MacroEventCoordinator(
        db_client=db_client,
        alpaca_api_key=alpaca_key,
        alpaca_secret_key=alpaca_secret,
        vertex_project_id=vertex_project,
        vertex_location=vertex_location,
        vertex_model_id=vertex_model
    )
