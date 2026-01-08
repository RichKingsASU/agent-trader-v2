import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from event_utils import (  # noqa: E402
    choose_doc_id,
    infer_topic,
    normalize_doc_id,
    ordering_ts,
    parse_ts,
)


class TestEventUtils(unittest.TestCase):
    def test_choose_doc_id_prefers_event_id(self) -> None:
        payload = {"eventId": "evt-123"}
        doc_id = choose_doc_id(payload=payload, message_id="msg-999")
        self.assertEqual(doc_id, "evt-123")

    def test_choose_doc_id_falls_back_to_message_id(self) -> None:
        payload = {"eventId": "   "}
        doc_id = choose_doc_id(payload=payload, message_id="msg-999")
        self.assertEqual(doc_id, "msg-999")

    def test_normalize_doc_id_strips_slashes(self) -> None:
        self.assertEqual(normalize_doc_id("a/b/c"), "a_b_c")

    def test_parse_ts_rfc3339_z(self) -> None:
        dt = parse_ts("2026-01-08T12:34:56.123Z")
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.year, 2026)

    def test_ordering_prefers_produced_at(self) -> None:
        pubsub = datetime(2026, 1, 8, 0, 0, tzinfo=timezone.utc)
        payload = {
            "publishedAt": "2026-01-08T00:01:00Z",
            "producedAt": "2026-01-08T00:02:00Z",
        }
        ts = ordering_ts(payload=payload, pubsub_published_at=pubsub)
        self.assertEqual(ts, datetime(2026, 1, 8, 0, 2, tzinfo=timezone.utc))

    def test_infer_topic_prefers_attributes(self) -> None:
        t = infer_topic(
            attributes={"topic": "market-ticks"},
            payload={"topic": "trade-signals"},
            subscription="projects/p/subscriptions/sub-1",
        )
        self.assertEqual(t, "market-ticks")

    def test_infer_topic_from_subscription_map(self) -> None:
        old = os.environ.get("SUBSCRIPTION_TOPIC_MAP")
        try:
            os.environ["SUBSCRIPTION_TOPIC_MAP"] = '{"sub-1":"market-bars-1m"}'
            t = infer_topic(
                attributes={},
                payload={},
                subscription="projects/p/subscriptions/sub-1",
            )
            self.assertEqual(t, "market-bars-1m")
        finally:
            if old is None:
                os.environ.pop("SUBSCRIPTION_TOPIC_MAP", None)
            else:
                os.environ["SUBSCRIPTION_TOPIC_MAP"] = old


if __name__ == "__main__":
    unittest.main()

