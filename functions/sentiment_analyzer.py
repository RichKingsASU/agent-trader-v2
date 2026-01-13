# ~/agenttrader_v2/functions/sentiment_analyzer.py

import os
import alpaca_trade_api as tradeapi
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import torch
import re
from datetime import datetime, timedelta

from functions.utils.apca_env import assert_paper_alpaca_base_url

"""
Strategy II: FinBERT Sentiment Analyzer

- Logic: Uses FinBERT for semantic analysis of Alpaca news feeds [cite: 67, 91].
- Rule: Implements "Reasoning-Driven" signals to avoid misinterpreting context [cite: 68, 69].
- Rebalancing: Designed to be called on a MONTHLY schedule to optimize Sharpe ratios and reduce fee erosion [cite: 78, 81].
"""

# --- Configuration ---
# It's recommended to use a model specifically fine-tuned for financial news.
MODEL_NAME = "ProsusAI/finbert"
NEWS_LOOKBACK_DAYS = 30 # Corresponds to monthly rebalancing period

class SentimentAnalyzer:
    """
    Analyzes market sentiment for a given stock ticker using FinBERT
    on news articles fetched from the Alpaca API.
    """
    def __init__(self):
        """
        Initializes the Alpaca API client and the FinBERT sentiment analysis pipeline.
        """
        try:
            # Initialize Alpaca API
            base_url = assert_paper_alpaca_base_url(
                os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
            )
            self.api = tradeapi.REST(
                os.environ.get('APCA_API_KEY_ID'),
                os.environ.get('APCA_API_SECRET_KEY'),
                base_url=base_url
            )
            print("✅ Alpaca API initialized successfully.")
        except Exception as e:
            print(f"🔥 Error initializing Alpaca API: {e}")
            self.api = None

        # Initialize FinBERT pipeline
        try:
            tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
            self.sentiment_pipeline = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)
            print("✅ FinBERT sentiment analysis pipeline loaded successfully.")
        except Exception as e:
            print(f"🔥 Error loading FinBERT model: {e}")
            self.sentiment_pipeline = None

    def _fetch_news(self, symbol: str) -> list:
        """
        Fetches news articles for a specific symbol from the last N days.
        [cite: 67, 91]
        """
        if not self.api:
            return []
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=NEWS_LOOKBACK_DAYS)
        
        try:
            news = self.api.get_news(
                symbol=symbol,
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d')
            )
            # The API returns news objects, we need the headlines
            return [n.headline for n in news]
        except Exception as e:
            print(f"🔥 Error fetching news for {symbol}: {e}")
            return []

    def _reasoning_driven_filter(self, headline: str, symbol: str) -> bool:
        """
        Applies a "Reasoning-Driven" filter to avoid misinterpreting context.
        This is a heuristic approach to ensure the news is relevant.
        [cite: 68, 69]

        - Checks if the stock's symbol is explicitly mentioned.
        - Filters out common "noise" phrases like "market update", "stocks to watch".
        """
        # Rule 1: Symbol must be in the headline (case-insensitive)
        if symbol.lower() not in headline.lower():
            return False
            
        # Rule 2: Filter out generic, non-specific headlines
        noise_phrases = [
            "stocks to watch", "market today", "analyst ratings",
            "earnings preview", "trade ideas"
        ]
        if any(phrase in headline.lower() for phrase in noise_phrases):
            return False
            
        return True

    def get_sentiment_signal(self, symbol: str) -> dict:
        """
        Generates a sentiment signal for a given stock symbol.

        The signal is an aggregation of sentiment scores from recent, relevant news.
        This function is designed to be called as part of a monthly rebalancing strategy.
        """
        if not self.sentiment_pipeline:
            return {"error": "Sentiment pipeline not initialized."}

        headlines = self._fetch_news(symbol)
        if not headlines:
            return {"symbol": symbol, "score": 0.0, "reason": "No recent news found."}

        sentiment_scores = []
        positive_headlines = []
        negative_headlines = []

        for h in headlines:
            if self._reasoning_driven_filter(h, symbol):
                # Analyze sentiment
                results = self.sentiment_pipeline([h])
                score_data = results[0]
                
                # Convert label to a numerical score: positive=1, neutral=0, negative=-1
                score = 0.0
                if score_data['label'] == 'positive':
                    score = score_data['score']
                    positive_headlines.append(h)
                elif score_data['label'] == 'negative':
                    score = -score_data['score']
                    negative_headlines.append(h)
                
                sentiment_scores.append(score)

        if not sentiment_scores:
            return {"symbol": symbol, "score": 0.0, "reason": "No relevant headlines after filtering."}

        # Aggregate score: simple average
        final_score = sum(sentiment_scores) / len(sentiment_scores)

        return {
            "symbol": symbol,
            "final_score": round(final_score, 4),
            "confidence": round(abs(final_score), 4),
            "relevant_articles": len(sentiment_scores),
            "positive_headlines": len(positive_headlines),
            "negative_headlines": len(negative_headlines),
            "reason": f"Aggregated sentiment from {len(sentiment_scores)} articles."
        }


if __name__ == '__main__':
    # This requires Alpaca environment variables to be set:
    # APCA_API_KEY_ID, APCA_API_SECRET_KEY
    
    print("🚀 Building Sentiment Analyzer Engine...")
    analyzer = SentimentAnalyzer()

    if analyzer.api and analyzer.sentiment_pipeline:
        print("\n--- Running Sentiment Analysis for AAPL ---")
        aapl_signal = analyzer.get_sentiment_signal("AAPL")
        print(aapl_signal)

        print("\n--- Running Sentiment Analysis for TSLA ---")
        tsla_signal = analyzer.get_sentiment_signal("TSLA")
        print(tsla_signal)
