import unittest
from datetime import datetime, timezone

from cloudrun_consumer.event_utils import choose_doc_id
from cloudrun_consumer.firestore_writer import apply_pubsub_lww


def _dt(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TestReplayIdempotency(unittest.TestCase):
    def test_replay_same_message_10x_stable_state(self) -> None:
        payload = {"eventId": "evt-1", "value": 123}
        message_id = "msg-1"
        published_at = _dt("2026-01-08T00:00:01Z")

        doc_id = choose_doc_id(payload=payload, message_id=message_id)
        self.assertEqual(doc_id, "evt-1")

        incoming = {
            "docId": doc_id,
            "data": payload,
            "lastAppliedMessageId": message_id,
            "lastAppliedPublishedAt": published_at,
            "source": {"messageId": message_id, "publishedAt": published_at},
        }

        store: dict[str, dict] = {}
        for _ in range(10):
            existing = store.get(doc_id)
            applied, new_doc = apply_pubsub_lww(
                existing=existing,
                incoming=incoming,
                published_at=published_at,
                message_id=message_id,
            )
            if applied:
                store[doc_id] = new_doc

        # Deterministic doc id => no duplicates.
        self.assertEqual(len(store), 1)
        self.assertEqual(store[doc_id]["data"], payload)
        self.assertEqual(store[doc_id]["lastAppliedMessageId"], message_id)

    def test_out_of_order_delivery_does_not_regress_state(self) -> None:
        payload_old = {"eventId": "evt-1", "value": 1}
        payload_new = {"eventId": "evt-1", "value": 2}
        doc_id = "evt-1"

        t_old = _dt("2026-01-08T00:00:01Z")
        t_new = _dt("2026-01-08T00:00:02Z")

        doc_new = {
            "docId": doc_id,
            "data": payload_new,
            "lastAppliedMessageId": "m2",
            "lastAppliedPublishedAt": t_new,
            "source": {"messageId": "m2", "publishedAt": t_new},
        }
        doc_old = {
            "docId": doc_id,
            "data": payload_old,
            "lastAppliedMessageId": "m1",
            "lastAppliedPublishedAt": t_old,
            "source": {"messageId": "m1", "publishedAt": t_old},
        }

        store: dict[str, dict] = {}
        applied1, d1 = apply_pubsub_lww(existing=None, incoming=doc_new, published_at=t_new, message_id="m2")
        self.assertTrue(applied1)
        store[doc_id] = d1

        applied2, d2 = apply_pubsub_lww(existing=store[doc_id], incoming=doc_old, published_at=t_old, message_id="m1")
        self.assertFalse(applied2)
        self.assertEqual(store[doc_id]["data"]["value"], 2)


if __name__ == "__main__":
    unittest.main()

