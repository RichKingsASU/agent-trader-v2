import unittest
from unittest.mock import MagicMock


from functions.utils import macro_scraper


class TestMacroScraperSafety(unittest.TestCase):
    def test_sanitize_llm_action_blocks_directional(self) -> None:
        self.assertEqual(macro_scraper._sanitize_llm_action("widen_stops"), "widen_stops")
        self.assertEqual(macro_scraper._sanitize_llm_action("BUY"), "pause_trading")
        self.assertEqual(macro_scraper._sanitize_llm_action("sell the rip"), "pause_trading")
        self.assertEqual(macro_scraper._sanitize_llm_action("go long"), "pause_trading")
        self.assertEqual(macro_scraper._sanitize_llm_action(None), "pause_trading")

    def test_parse_analysis_response_sanitizes_llm_fields(self) -> None:
        analyzer = macro_scraper.GeminiMacroAnalyzer(project_id="test")
        release = macro_scraper.EconomicRelease(
            event_name="CPI",
            release_time=macro_scraper.datetime.now(macro_scraper.timezone.utc),
            actual_value=3.5,
            expected_value=3.0,
        )
        raw = """{
          "is_significant_surprise": true,
          "surprise_magnitude": 0.5,
          "market_impact": "super bullish",
          "volatility_expectation": "bananas",
          "recommended_action": "buy_the_dip",
          "confidence_score": 0.9,
          "reasoning": "test"
        }"""
        analysis = analyzer._parse_analysis_response(raw, release)
        self.assertTrue(analysis.is_significant_surprise)
        self.assertEqual(analysis.recommended_action, "pause_trading")
        self.assertEqual(analysis.volatility_expectation, "high")
        self.assertEqual(analysis.market_impact, "neutral")

    def test_update_market_regime_does_not_persist_direction(self) -> None:
        # Arrange a minimal Firestore-like mock chain:
        db = MagicMock()
        regime_ref = MagicMock()
        db.collection.return_value.document.return_value = regime_ref

        current_doc = MagicMock()
        current_doc.exists = False
        current_doc.to_dict.return_value = {}
        regime_ref.get.return_value = current_doc

        coordinator = macro_scraper.MacroEventCoordinator(
            db_client=db,
            alpaca_api_key="test",
            alpaca_secret_key="test",
            vertex_project_id="test",
        )

        events = [
            {
                "release": {"event_name": "CPI", "release_time": "2026-01-01T00:00:00Z", "source": "FRED"},
                "analysis": {
                    "surprise_magnitude": 0.5,
                    "volatility_expectation": "high",
                    "recommended_action": "SELL",
                    "confidence_score": 0.9,
                    "reasoning": "test",
                    "market_impact": "bearish",
                },
                "related_news_count": 0,
            }
        ]

        # Act
        coordinator._update_market_regime(macro_scraper.MarketRegimeStatus.VOLATILITY_EVENT, events)

        # Assert: regime doc contains only regime-safe event fields
        args, kwargs = regime_ref.set.call_args
        self.assertTrue(kwargs.get("merge"))
        regime_payload = args[0]
        self.assertIn("macro_events", regime_payload)
        self.assertEqual(regime_payload["macro_events"][0]["recommended_action"], "pause_trading")
        self.assertNotIn("market_impact", regime_payload["macro_events"][0])

    def test_archive_event_strips_market_impact(self) -> None:
        db = MagicMock()
        # doc().collection().document()
        doc = MagicMock()
        db.collection.return_value.document.return_value = doc
        macro_events_coll = MagicMock()
        doc.collection.return_value = macro_events_coll
        macro_doc = MagicMock()
        macro_events_coll.document.return_value = macro_doc

        coordinator = macro_scraper.MacroEventCoordinator(
            db_client=db,
            alpaca_api_key="test",
            alpaca_secret_key="test",
            vertex_project_id="test",
        )

        events = [
            {
                "release": {"event_name": "CPI", "release_time": "2026-01-01T00:00:00Z", "source": "FRED"},
                "analysis": {
                    "is_significant_surprise": True,
                    "surprise_magnitude": 0.5,
                    "volatility_expectation": "high",
                    "recommended_action": "normal",
                    "confidence_score": 0.9,
                    "reasoning": "test",
                    "market_impact": "bearish",
                },
                "related_news_count": 1,
            }
        ]

        coordinator._archive_event(events)

        args, _ = macro_doc.set.call_args
        archived = args[0]
        self.assertIn("analysis", archived)
        self.assertNotIn("market_impact", archived["analysis"])


if __name__ == "__main__":
    unittest.main()

