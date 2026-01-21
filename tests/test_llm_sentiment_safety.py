import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest


def test_hold_on_missing_news():
    from backend.strategy_engine.strategies import llm_sentiment_alpha as strat

    out = asyncio.run(strat.make_decision(news_items=[], symbol="SPY"))
    assert out["action"] == "flat"
    payload = out["signal_payload"]
    assert payload["safety"]["posture"] == "HOLD_FAIL_CLOSED"
    assert payload["safety"]["blocked"] is True


def test_no_future_leakage_filters_future_news(monkeypatch):
    from backend.strategy_engine.strategies import llm_sentiment_alpha as strat

    now = datetime.now(timezone.utc)
    news = [
        strat.NewsItem(
            headline="Future headline",
            source="Alpaca",
            timestamp=now + timedelta(hours=24),
            symbol="SPY",
        )
    ]

    out = asyncio.run(strat.make_decision(news_items=news, symbol="SPY"))
    assert out["action"] == "flat"
    payload = out["signal_payload"]
    assert payload["safety"]["posture"] == "HOLD_FAIL_CLOSED"
    dropped = payload["input_review"]["news"]["dropped"]
    assert dropped["future_dated"] >= 1


def test_hold_on_stale_news_via_threshold(monkeypatch):
    from backend.strategy_engine.strategies import llm_sentiment_alpha as strat

    monkeypatch.setenv("STRATEGY_NEWS_STALE_SECONDS", "60")
    now = datetime.now(timezone.utc)
    news = [
        strat.NewsItem(
            headline="Old but within lookback",
            source="Alpaca",
            timestamp=now - timedelta(minutes=5),
            symbol="SPY",
        )
    ]

    out = asyncio.run(strat.make_decision(news_items=news, symbol="SPY"))
    assert out["action"] == "flat"
    payload = out["signal_payload"]
    assert payload["safety"]["posture"] == "HOLD_FAIL_CLOSED"
    assert "Stale news" in out["reason"]


def test_confidence_threshold_blocks_and_attaches_explanation(monkeypatch):
    from backend.strategy_engine.strategies import llm_sentiment_alpha as strat

    def fake_analyze(news_items, symbol, model_id="gemini-1.5-flash"):
        return strat.SentimentAnalysis(
            sentiment_score=0.95,
            confidence=0.2,
            reasoning="Low confidence.",
            cash_flow_impact="Unclear.",
            action="HOLD",
            target_symbols=[symbol],
        )

    monkeypatch.setattr(strat, "analyze_sentiment_with_gemini", fake_analyze)

    now = datetime.now(timezone.utc)
    news = [
        strat.NewsItem(
            headline="Fresh headline",
            source="Alpaca",
            timestamp=now - timedelta(minutes=1),
            symbol="SPY",
        )
    ]

    out = asyncio.run(
        strat.make_decision(news_items=news, symbol="SPY", sentiment_threshold=0.7, confidence_threshold=0.8)
    )
    assert out["action"] == "flat"
    payload = out["signal_payload"]
    assert payload["safety"]["posture"] == "OBSERVE_SAFE"
    assert payload["safety"]["blocked"] is True
    assert isinstance(payload.get("explanation", {}).get("summary"), str)


def test_no_trade_amplification_caps_intent_confidence(monkeypatch):
    from backend.strategy_engine.strategies import llm_sentiment_alpha as strat

    def fake_analyze(news_items, symbol, model_id="gemini-1.5-flash"):
        return strat.SentimentAnalysis(
            sentiment_score=0.95,
            confidence=0.95,
            reasoning="Very confident positive.",
            cash_flow_impact="Positive.",
            action="BUY",
            target_symbols=[symbol],
        )

    monkeypatch.setattr(strat, "analyze_sentiment_with_gemini", fake_analyze)

    now = datetime.now(timezone.utc)
    news = [
        strat.NewsItem(
            headline="Fresh headline",
            source="Alpaca",
            timestamp=now - timedelta(minutes=1),
            symbol="SPY",
        )
    ]

    out = asyncio.run(
        strat.make_decision(news_items=news, symbol="SPY", sentiment_threshold=0.7, confidence_threshold=0.8)
    )
    assert out["action"] == "buy"
    payload = out["signal_payload"]
    # Capped to threshold (no amplification)
    assert payload["confidence"] == pytest.approx(0.8)
    assert payload["raw_confidence"] == pytest.approx(0.95)
    assert payload["safety"]["no_trade_amplification"] is True

