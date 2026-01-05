#!/usr/bin/env python3
"""
Test Script for Macro-Event Scraper

This script tests the macro scraper functionality locally without deploying.

Usage:
    python scripts/test_macro_scraper.py
"""

import os
import sys
from datetime import datetime, timezone

# Add functions to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'functions'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    
    try:
        from functions.utils.macro_scraper import (
            EconomicRelease,
            NewsAlert,
            MacroAnalysis,
            EventSeverity,
            MarketRegimeStatus,
            FedEconomicCalendarScraper,
            AlpacaMacroNewsFetcher,
            GeminiMacroAnalyzer,
            MacroEventCoordinator,
            MAJOR_ECONOMIC_EVENTS,
        )
        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_economic_events_config():
    """Test economic events configuration"""
    print("\nTesting economic events configuration...")
    
    from functions.utils.macro_scraper import MAJOR_ECONOMIC_EVENTS, EventSeverity
    
    required_events = ["CPI", "FOMC", "NFP", "GDP", "PCE", "UNEMPLOYMENT"]
    
    for event in required_events:
        if event not in MAJOR_ECONOMIC_EVENTS:
            print(f"✗ Missing event: {event}")
            return False
        
        config = MAJOR_ECONOMIC_EVENTS[event]
        assert "full_name" in config
        assert "keywords" in config
        assert "surprise_threshold" in config
        assert "severity" in config
        print(f"✓ {event}: {config['full_name']} (threshold: {config['surprise_threshold']})")
    
    print(f"✓ All {len(MAJOR_ECONOMIC_EVENTS)} events configured correctly")
    return True


def test_data_classes():
    """Test data class creation"""
    print("\nTesting data classes...")
    
    from functions.utils.macro_scraper import (
        EconomicRelease,
        NewsAlert,
        MacroAnalysis,
        EventSeverity,
    )
    
    # Test EconomicRelease
    release = EconomicRelease(
        event_name="CPI",
        release_time=datetime.now(timezone.utc),
        actual_value=3.5,
        expected_value=3.0,
        surprise_magnitude=16.67,
        severity=EventSeverity.HIGH
    )
    assert release.event_name == "CPI"
    assert release.surprise_magnitude == 16.67
    print("✓ EconomicRelease creation works")
    
    # Test NewsAlert
    alert = NewsAlert(
        headline="Fed Raises Rates",
        source="Reuters",
        timestamp=datetime.now(timezone.utc),
        symbols=["SPY"]
    )
    assert "Fed" in alert.headline
    print("✓ NewsAlert creation works")
    
    # Test MacroAnalysis
    analysis = MacroAnalysis(
        event_name="CPI",
        is_significant_surprise=True,
        surprise_magnitude=0.5,
        market_impact="bearish",
        volatility_expectation="high",
        recommended_action="widen_stops",
        confidence_score=0.85,
        reasoning="Test reasoning",
        timestamp=datetime.now(timezone.utc)
    )
    assert analysis.is_significant_surprise is True
    assert analysis.confidence_score == 0.85
    print("✓ MacroAnalysis creation works")
    
    return True


def test_scraper_initialization():
    """Test scraper components can be initialized"""
    print("\nTesting scraper initialization...")
    
    from functions.utils.macro_scraper import FedEconomicCalendarScraper
    
    scraper = FedEconomicCalendarScraper()
    assert scraper.session is not None
    print("✓ FedEconomicCalendarScraper initialized")
    
    # Note: Can't test AlpacaMacroNewsFetcher without credentials
    # Note: Can't test GeminiMacroAnalyzer without GCP setup
    
    return True


def test_news_relevance():
    """Test macro news relevance detection"""
    print("\nTesting news relevance detection...")
    
    from functions.utils.macro_scraper import AlpacaMacroNewsFetcher
    
    # Create fetcher (won't make API calls, just test logic)
    fetcher = AlpacaMacroNewsFetcher(api_key="test", secret_key="test")
    
    macro_headlines = [
        "Federal Reserve Raises Interest Rates",
        "CPI Inflation Data Released",
        "Jobs Report Shows Strong Employment",
        "Powell Signals Rate Cuts Ahead",
    ]
    
    non_macro_headlines = [
        "Apple Announces New iPhone",
        "Tesla Stock Rises on Earnings",
        "Netflix Adds Subscribers",
    ]
    
    # Test macro headlines
    for headline in macro_headlines:
        if not fetcher._is_macro_relevant(headline):
            print(f"✗ False negative: {headline}")
            return False
    print(f"✓ Correctly identified {len(macro_headlines)} macro headlines")
    
    # Test non-macro headlines
    for headline in non_macro_headlines:
        if fetcher._is_macro_relevant(headline):
            print(f"✗ False positive: {headline}")
            return False
    print(f"✓ Correctly filtered {len(non_macro_headlines)} non-macro headlines")
    
    return True


def test_regime_determination():
    """Test market regime determination logic"""
    print("\nTesting regime determination...")
    
    from functions.utils.macro_scraper import MacroEventCoordinator, MarketRegimeStatus
    from unittest.mock import Mock
    
    # Create mock coordinator
    mock_db = Mock()
    coordinator = MacroEventCoordinator(
        db_client=mock_db,
        alpaca_api_key="test",
        alpaca_secret_key="test",
        vertex_project_id="test"
    )
    
    # Test normal (no events)
    regime = coordinator._determine_regime_status([])
    assert regime == MarketRegimeStatus.NORMAL
    print("✓ Normal regime determination works")
    
    # Test volatility event (1 high event)
    events = [{
        "release": {"event_name": "CPI"},
        "analysis": {"volatility_expectation": "high", "surprise_magnitude": 0.5}
    }]
    regime = coordinator._determine_regime_status(events)
    assert regime == MarketRegimeStatus.VOLATILITY_EVENT
    print("✓ Volatility event determination works")
    
    # Test extreme volatility
    events = [{
        "release": {"event_name": "FOMC"},
        "analysis": {"volatility_expectation": "extreme", "surprise_magnitude": 1.0}
    }]
    regime = coordinator._determine_regime_status(events)
    assert regime == MarketRegimeStatus.EXTREME_VOLATILITY
    print("✓ Extreme volatility determination works")
    
    return True


def test_multipliers():
    """Test stop-loss and position size multiplier calculations"""
    print("\nTesting multiplier calculations...")
    
    from functions.utils.macro_scraper import MacroEventCoordinator, MarketRegimeStatus
    from unittest.mock import Mock
    
    mock_db = Mock()
    coordinator = MacroEventCoordinator(
        db_client=mock_db,
        alpaca_api_key="test",
        alpaca_secret_key="test",
        vertex_project_id="test"
    )
    
    # Test stop-loss multipliers
    assert coordinator._calculate_stop_loss_multiplier(MarketRegimeStatus.NORMAL) == 1.0
    assert coordinator._calculate_stop_loss_multiplier(MarketRegimeStatus.VOLATILITY_EVENT) == 1.5
    assert coordinator._calculate_stop_loss_multiplier(MarketRegimeStatus.HIGH_VOLATILITY) == 2.0
    assert coordinator._calculate_stop_loss_multiplier(MarketRegimeStatus.EXTREME_VOLATILITY) == 2.5
    print("✓ Stop-loss multipliers: 1.0x → 1.5x → 2.0x → 2.5x")
    
    # Test position size multipliers
    assert coordinator._calculate_position_size_multiplier(MarketRegimeStatus.NORMAL) == 1.0
    assert coordinator._calculate_position_size_multiplier(MarketRegimeStatus.VOLATILITY_EVENT) == 0.75
    assert coordinator._calculate_position_size_multiplier(MarketRegimeStatus.HIGH_VOLATILITY) == 0.50
    assert coordinator._calculate_position_size_multiplier(MarketRegimeStatus.EXTREME_VOLATILITY) == 0.25
    print("✓ Position size multipliers: 1.0x → 0.75x → 0.50x → 0.25x")
    
    return True


def main():
    """Run all tests"""
    print("=" * 70)
    print("Macro-Event Scraper Test Suite")
    print("=" * 70)
    
    tests = [
        ("Imports", test_imports),
        ("Economic Events Config", test_economic_events_config),
        ("Data Classes", test_data_classes),
        ("Scraper Initialization", test_scraper_initialization),
        ("News Relevance", test_news_relevance),
        ("Regime Determination", test_regime_determination),
        ("Multipliers", test_multipliers),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"\n✗ {name} FAILED")
        except Exception as e:
            failed += 1
            print(f"\n✗ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed == 0:
        print("\n✅ All tests passed!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
