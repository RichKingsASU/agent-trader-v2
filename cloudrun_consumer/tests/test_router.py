import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schema_router import route_payload  # noqa: E402


class TestRouter(unittest.TestCase):
    def test_system_events_shape_wins(self) -> None:
        payload = {"service": "svc-a", "timestamp": "2026-01-08T00:00:00Z"}
        h = route_payload(payload=payload, attributes={}, topic="market-ticks")
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h.name, "system_events")

    def test_routes_market_ticks_by_topic(self) -> None:
        payload = {"eventId": "evt-1", "symbol": "SPY"}
        h = route_payload(payload=payload, attributes={}, topic="market-ticks")
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h.name, "market_ticks")

    def test_routes_market_bars_by_topic(self) -> None:
        payload = {"eventId": "evt-2", "symbol": "SPY"}
        h = route_payload(payload=payload, attributes={}, topic="market-bars-1m")
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h.name, "market_bars_1m")

    def test_routes_trade_signals_by_topic(self) -> None:
        payload = {"eventId": "evt-3", "symbol": "SPY"}
        h = route_payload(payload=payload, attributes={}, topic="trade-signals")
        self.assertIsNotNone(h)
        assert h is not None
        self.assertEqual(h.name, "trade_signals")


if __name__ == "__main__":
    unittest.main()

