"""
Tests for Congressional Alpha Tracker Strategy
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

# Import strategy module
import sys
from pathlib import Path

strategy_path = Path(__file__).parent.parent / "backend" / "strategy_runner" / "examples" / "congressional_alpha"
sys.path.insert(0, str(strategy_path))

import strategy as congressional_alpha


class TestCongressionalAlphaStrategy:
    """Test suite for Congressional Alpha Tracker strategy."""
    
    def test_policy_whales_configuration(self):
        """Test that policy whales are properly configured."""
        assert "Nancy Pelosi" in congressional_alpha.POLICY_WHALES
        assert "Tommy Tuberville" in congressional_alpha.POLICY_WHALES
        
        pelosi_config = congressional_alpha.POLICY_WHALES["Nancy Pelosi"]
        assert pelosi_config["weight_multiplier"] == 1.5
        assert "min_confidence" in pelosi_config
    
    def test_committee_weights_configuration(self):
        """Test that committee weights are properly configured."""
        assert "Armed Services" in congressional_alpha.COMMITTEE_WEIGHTS
        assert "Financial Services" in congressional_alpha.COMMITTEE_WEIGHTS
        
        armed_services = congressional_alpha.COMMITTEE_WEIGHTS["Armed Services"]
        assert "tickers" in armed_services
        assert "bonus" in armed_services
        assert "LMT" in armed_services["tickers"]
    
    def test_high_conviction_tickers(self):
        """Test that high-conviction tickers are defined."""
        assert "NVDA" in congressional_alpha.HIGH_CONVICTION_TICKERS
        assert "AAPL" in congressional_alpha.HIGH_CONVICTION_TICKERS
        assert "LMT" in congressional_alpha.HIGH_CONVICTION_TICKERS
    
    def test_calculate_committee_weight_with_relevant_committee(self):
        """Test committee weight calculation for relevant committee."""
        # Armed Services + LMT (defense stock)
        weight = congressional_alpha.calculate_committee_weight(
            committees=["Armed Services"],
            ticker="LMT"
        )
        assert weight > 0
        assert weight == 0.4  # Armed Services bonus
    
    def test_calculate_committee_weight_with_irrelevant_committee(self):
        """Test committee weight calculation for irrelevant committee."""
        # Agriculture + NVDA (tech stock)
        weight = congressional_alpha.calculate_committee_weight(
            committees=["Agriculture"],
            ticker="NVDA"
        )
        assert weight == 0.0
    
    def test_calculate_committee_weight_with_multiple_committees(self):
        """Test committee weight calculation with multiple relevant committees."""
        # Financial Services + Science & Tech + AAPL
        weight = congressional_alpha.calculate_committee_weight(
            committees=["Financial Services", "Science, Space, and Technology"],
            ticker="AAPL"
        )
        assert weight >= 0.35  # Both committees are relevant to AAPL
    
    def test_calculate_committee_weight_capped_at_100_percent(self):
        """Test that committee weight bonus is capped at 100%."""
        # Add many committees to test cap
        weight = congressional_alpha.calculate_committee_weight(
            committees=["Appropriations", "Financial Services", "Armed Services"],
            ticker="*"
        )
        assert weight <= 1.0  # Cap at 100%
    
    def test_calculate_position_size(self):
        """Test position size calculation."""
        size = congressional_alpha.calculate_position_size(
            transaction_amount_midpoint=75000.0,
            whale_multiplier=1.5,
            committee_bonus=0.3,
            is_high_conviction=True,
        )
        
        # Base: 75000 * 0.1 = 7500
        # Whale: 7500 * 1.5 = 11250
        # Committee: 11250 * 1.3 = 14625
        # High conviction: 14625 * 1.3 = 19012.5
        assert size > 15000
        assert size < 25000
    
    def test_calculate_position_size_minimum_floor(self):
        """Test that position size has minimum floor."""
        size = congressional_alpha.calculate_position_size(
            transaction_amount_midpoint=100.0,  # Very small
            whale_multiplier=1.0,
            committee_bonus=0.0,
            is_high_conviction=False,
        )
        assert size >= 1000.0  # Min floor
    
    def test_calculate_position_size_maximum_cap(self):
        """Test that position size has maximum cap."""
        size = congressional_alpha.calculate_position_size(
            transaction_amount_midpoint=10000000.0,  # Very large
            whale_multiplier=2.0,
            committee_bonus=1.0,
            is_high_conviction=True,
        )
        assert size <= 50000.0  # Max cap
    
    def test_calculate_confidence(self):
        """Test confidence calculation."""
        confidence = congressional_alpha.calculate_confidence(
            whale_multiplier=1.5,
            committee_bonus=0.4,
            is_high_conviction=True,
            transaction_amount=100000.0,
        )
        
        # Should be high confidence
        assert confidence > 0.7
        assert confidence <= 0.95  # Capped
    
    def test_calculate_confidence_low_case(self):
        """Test confidence calculation for low-confidence scenario."""
        confidence = congressional_alpha.calculate_confidence(
            whale_multiplier=1.2,
            committee_bonus=0.0,
            is_high_conviction=False,
            transaction_amount=20000.0,
        )
        
        # Should be lower confidence
        assert confidence < 0.7
    
    def test_on_market_event_nancy_pelosi_nvda_purchase(self):
        """Test strategy with Nancy Pelosi buying NVDA (high-conviction)."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_001",
            "ts": "2024-12-30T10:30:00Z",
            "symbol": "NVDA",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Nancy Pelosi",
                "politician_id": "pelosi_nancy",
                "chamber": "house",
                "transaction_type": "purchase",
                "transaction_date": "2024-12-27T00:00:00Z",
                "disclosure_date": "2024-12-30T00:00:00Z",
                "amount_range": "$50,001 - $100,000",
                "amount_min": 50001.0,
                "amount_max": 100000.0,
                "amount_midpoint": 75000.0,
                "committees": ["Financial Services", "Select Committee on Intelligence"],
                "party": "D",
                "state": "CA",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        assert intents is not None
        assert len(intents) == 1
        
        intent = intents[0]
        assert intent["symbol"] == "NVDA"
        assert intent["side"] == "buy"
        assert intent["order_type"] == "market"
        assert intent["client_tag"] == "congressional_alpha"
        
        metadata = intent["metadata"]
        assert metadata["politician"] == "Nancy Pelosi"
        assert metadata["whale_multiplier"] == 1.5
        assert metadata["is_high_conviction"] is True
        assert metadata["confidence"] > 0.7
        assert "reasoning" in metadata
    
    def test_on_market_event_tuberville_lmt_with_committee_bonus(self):
        """Test strategy with Tuberville buying LMT (Armed Services member)."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_002",
            "ts": "2024-12-30T11:00:00Z",
            "symbol": "LMT",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Tommy Tuberville",
                "politician_id": "tuberville_tommy",
                "chamber": "senate",
                "transaction_type": "purchase",
                "transaction_date": "2024-12-28T00:00:00Z",
                "disclosure_date": "2024-12-30T00:00:00Z",
                "amount_range": "$100,001 - $250,000",
                "amount_min": 100001.0,
                "amount_max": 250000.0,
                "amount_midpoint": 175000.0,
                "committees": ["Armed Services", "Agriculture"],
                "party": "R",
                "state": "AL",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        assert intents is not None
        assert len(intents) == 1
        
        intent = intents[0]
        assert intent["symbol"] == "LMT"
        
        metadata = intent["metadata"]
        assert metadata["committee_bonus"] > 0  # Should have Armed Services bonus
        assert metadata["confidence"] > 0.7  # High confidence
    
    def test_on_market_event_filters_sales_when_purchase_only(self):
        """Test that sales are filtered when PURCHASE_ONLY is True."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_003",
            "ts": "2024-12-30T13:00:00Z",
            "symbol": "TSLA",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Nancy Pelosi",
                "politician_id": "pelosi_nancy",
                "chamber": "house",
                "transaction_type": "sale",
                "transaction_date": "2024-12-28T00:00:00Z",
                "disclosure_date": "2024-12-30T00:00:00Z",
                "amount_range": "$25,001 - $50,000",
                "amount_min": 25001.0,
                "amount_max": 50000.0,
                "amount_midpoint": 37500.0,
                "committees": ["Financial Services"],
                "party": "D",
                "state": "CA",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        # Should filter out sales
        assert intents is None
    
    def test_on_market_event_filters_non_whales(self):
        """Test that non-whale politicians are filtered."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_004",
            "ts": "2024-12-30T14:00:00Z",
            "symbol": "META",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Unknown Representative",
                "politician_id": "unknown_rep",
                "chamber": "house",
                "transaction_type": "purchase",
                "transaction_date": "2024-12-28T00:00:00Z",
                "disclosure_date": "2024-12-30T00:00:00Z",
                "amount_range": "$50,001 - $100,000",
                "amount_min": 50001.0,
                "amount_max": 100000.0,
                "amount_midpoint": 75000.0,
                "committees": ["Education and Labor"],
                "party": "D",
                "state": "NY",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        # Should filter out non-whales
        assert intents is None
    
    def test_on_market_event_filters_small_transactions(self):
        """Test that transactions below minimum size are filtered."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_005",
            "ts": "2024-12-30T15:00:00Z",
            "symbol": "MSFT",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Nancy Pelosi",
                "politician_id": "pelosi_nancy",
                "chamber": "house",
                "transaction_type": "purchase",
                "transaction_date": "2024-12-29T00:00:00Z",
                "disclosure_date": "2024-12-30T00:00:00Z",
                "amount_range": "$1,001 - $15,000",
                "amount_min": 1001.0,
                "amount_max": 15000.0,
                "amount_midpoint": 8000.0,  # Below MIN_TRANSACTION_SIZE
                "committees": ["Financial Services"],
                "party": "D",
                "state": "CA",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        # Should filter out small transactions
        assert intents is None
    
    def test_on_market_event_ignores_non_congressional_events(self):
        """Test that non-congressional market events are ignored."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_006",
            "ts": "2024-12-30T16:00:00Z",
            "symbol": "AAPL",
            "source": "alpaca_trades",  # Different source
            "payload": {
                "price": 150.0,
                "volume": 1000,
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        # Should ignore non-congressional events
        assert intents is None
    
    def test_helper_function_get_tracked_politicians(self):
        """Test helper function to get tracked politicians."""
        politicians = congressional_alpha.get_tracked_politicians()
        
        assert isinstance(politicians, list)
        assert len(politicians) > 0
        assert "Nancy Pelosi" in politicians
        assert "Tommy Tuberville" in politicians
    
    def test_helper_function_get_committee_tickers(self):
        """Test helper function to get committee tickers."""
        tickers = congressional_alpha.get_committee_tickers("Armed Services")
        
        assert isinstance(tickers, list)
        assert "LMT" in tickers
        assert "RTX" in tickers
    
    def test_helper_function_is_high_conviction_ticker(self):
        """Test helper function to check high-conviction tickers."""
        assert congressional_alpha.is_high_conviction_ticker("NVDA") is True
        assert congressional_alpha.is_high_conviction_ticker("AAPL") is True
        assert congressional_alpha.is_high_conviction_ticker("XYZ") is False
    
    def test_helper_function_get_politician_stats(self):
        """Test helper function to get politician stats."""
        stats = congressional_alpha.get_politician_stats("Nancy Pelosi")
        
        assert stats is not None
        assert stats["name"] == "Nancy Pelosi"
        assert stats["weight_multiplier"] == 1.5
        assert stats["is_tracked"] is True
        
        # Non-existent politician
        stats_none = congressional_alpha.get_politician_stats("Unknown Person")
        assert stats_none is None
    
    def test_metadata_contains_reasoning(self):
        """Test that order intent metadata contains reasoning."""
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_test_007",
            "ts": "2024-12-30T10:30:00Z",
            "symbol": "AAPL",
            "source": "congressional_disclosure",
            "payload": {
                "politician": "Josh Gottheimer",
                "politician_id": "gottheimer_josh",
                "chamber": "house",
                "transaction_type": "purchase",
                "amount_range": "$50,001 - $100,000",
                "amount_min": 50001.0,
                "amount_max": 100000.0,
                "amount_midpoint": 75000.0,
                "committees": ["Financial Services"],
                "party": "D",
                "state": "NJ",
            }
        }
        
        intents = congressional_alpha.on_market_event(event)
        
        assert intents is not None
        intent = intents[0]
        reasoning = intent["metadata"]["reasoning"]
        
        assert "Josh Gottheimer" in reasoning
        assert "AAPL" in reasoning
        assert "Confidence:" in reasoning
        assert "multiplier" in reasoning


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
