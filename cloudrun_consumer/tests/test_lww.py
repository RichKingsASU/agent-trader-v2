from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from cloudrun_consumer.firestore_writer import _existing_pubsub_lww, _lww_key


def _dt(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TestLww(unittest.TestCase):
    def test_lww_key_orders_by_published_at_then_message_id(self) -> None:
        a = _lww_key(published_at=_dt("2026-01-08T00:00:00Z"), message_id="a")
        b = _lww_key(published_at=_dt("2026-01-08T00:00:00Z"), message_id="b")
        c = _lww_key(published_at=_dt("2026-01-08T00:00:01Z"), message_id="0")
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_existing_pubsub_lww_reads_multiple_shapes(self) -> None:
        pub, mid = _existing_pubsub_lww(
            {
                "published_at": _dt("2026-01-08T01:02:03Z"),
                "source": {"message_id": "m1"},
            }
        )
        self.assertEqual(pub, _dt("2026-01-08T01:02:03Z"))
        self.assertEqual(mid, "m1")

        pub2, mid2 = _existing_pubsub_lww(
            {
                "source": {"publishedAt": "2026-01-08T01:02:03Z", "messageId": "m2"},
            }
        )
        self.assertEqual(pub2, _dt("2026-01-08T01:02:03Z"))
        self.assertEqual(mid2, "m2")


if __name__ == "__main__":
    unittest.main()

