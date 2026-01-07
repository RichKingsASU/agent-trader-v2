from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.news_analysis import EventType, classify_event, relevance, sentiment, to_feature_records


def test_sentiment_deterministic_positive_example():
    text = "ACME beats earnings expectations and raises guidance for FY2026."
    s1 = sentiment(text)
    s2 = sentiment(text)
    assert s1 == s2
    # Fixed expectation: should be clearly positive but not saturated.
    assert pytest.approx(s1, abs=1e-12) == 0.8554666127777011


def test_sentiment_deterministic_negative_example():
    text = "ACME faces SEC investigation and lawsuit over accounting fraud."
    s1 = sentiment(text)
    s2 = sentiment(text)
    assert s1 == s2
    assert pytest.approx(s1, abs=1e-12) == -0.86049224526561


def test_classify_event_examples():
    assert classify_event("Company to acquire rival in $2B merger") == EventType.MERGER_ACQUISITION
    assert classify_event("ACME reports Q4 earnings results and EPS beats estimates") == EventType.EARNINGS
    assert classify_event("ACME raises guidance and issues upbeat outlook") == EventType.GUIDANCE
    assert classify_event("SEC opens investigation into ACME accounting") == EventType.REGULATORY
    assert classify_event("ACME sued in class action lawsuit") == EventType.LITIGATION
    assert classify_event("Bank upgrades ACME; raises price target") == EventType.ANALYST_RATING


def test_relevance_requires_symbol_mention_or_structured_match():
    sym = "AAPL"
    news = {"headline": "Big tech rally continues", "body": "Markets are higher", "symbol": None}
    assert relevance(sym, news) == 0.0


def test_relevance_uses_headline_mention_and_event_prior():
    sym = "AAPL"
    news = {
        "event_ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "source": "test",
        "symbol": "AAPL",
        "headline": "AAPL beats earnings expectations, raises guidance",
        "body": "More details inside.",
        "url": "https://example.test/aapl",
    }
    r = relevance(sym, news)
    assert 0.75 <= r <= 1.0


def test_to_feature_records_shape_and_ids_are_stable():
    news = {
        "event_ts": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "source": "test",
        "symbol": "AAPL",
        "headline": "AAPL launches new product",
        "body": "The launch is expected next month.",
        "url": "https://example.test/aapl2",
    }
    recs1 = to_feature_records("AAPL", news)
    recs2 = to_feature_records("AAPL", news)

    assert [r.feature_name for r in recs1] == ["news.sentiment", "news.event_type", "news.relevance"]
    assert [r.feature_id for r in recs1] == [r.feature_id for r in recs2]

    as_dict = {r.feature_name: r.to_dict() for r in recs1}
    assert as_dict["news.event_type"]["feature_value"] in {EventType.PRODUCT.value, EventType.OTHER.value}
    assert isinstance(as_dict["news.sentiment"]["feature_value"], float)
    assert isinstance(as_dict["news.relevance"]["feature_value"], float)

