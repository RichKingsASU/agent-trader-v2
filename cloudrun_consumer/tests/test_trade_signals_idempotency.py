import unittest
from datetime import datetime, timezone

from cloudrun_consumer.replay_support import ReplayContext, ensure_event_not_applied
from cloudrun_consumer.schema_router import route_payload
from cloudrun_consumer.handlers.trade_signals import choose_trade_signal_dedupe_key


class _FakeSnapshot:
    def __init__(self, *, exists: bool, data: dict | None) -> None:
        self.exists = bool(exists)
        self._data = data

    def to_dict(self) -> dict | None:
        return self._data


class _FakeDocRef:
    def __init__(self, *, store: dict[str, dict], path: str) -> None:
        self._store = store
        self._path = path

    def get(self, *, transaction: object) -> _FakeSnapshot:  # noqa: ARG002 - matches firestore shape
        exists = self._path in self._store
        data = self._store.get(self._path)
        return _FakeSnapshot(exists=exists, data=dict(data) if isinstance(data, dict) else None)


class _FakeCollectionRef:
    def __init__(self, *, store: dict[str, dict], name: str) -> None:
        self._store = store
        self._name = name

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(store=self._store, path=f"{self._name}/{doc_id}")


class _FakeTransaction:
    def __init__(self, *, store: dict[str, dict]) -> None:
        self._store = store

    def create(self, ref: _FakeDocRef, doc: dict) -> None:
        # Firestore create() fails if doc exists; for these unit tests,
        # we rely on the pre-read path to avoid calling create twice.
        self._store[ref._path] = dict(doc)


class _FakeDB:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollectionRef:
        return _FakeCollectionRef(store=self._store, name=name)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(store=self._store)


class _FakeFirestoreModule:
    @staticmethod
    def transactional(fn):
        def _runner(txn):
            return fn(txn)

        return _runner


class _FakeWriter:
    def __init__(self) -> None:
        self._db = _FakeDB()
        self._firestore = _FakeFirestoreModule()

        self.upsert_calls = 0

    @staticmethod
    def _col(name: str) -> str:
        return name

    def upsert_trade_signal(self, **kwargs):  # noqa: ANN003 - test double
        self.upsert_calls += 1
        return True, "applied"


class TestTradeSignalsIdempotency(unittest.TestCase):
    def test_same_message_id_redelivery_does_not_rerun_handler_side_effects(self) -> None:
        payload = {"eventId": "evt-1", "symbol": "SPY", "action": "BUY"}
        routed = route_payload(payload=payload, attributes={}, topic="trade-signals")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertEqual(routed.name, "trade_signals")

        writer = _FakeWriter()
        now = datetime.now(timezone.utc)

        r1 = routed.handler(
            payload=payload,
            env="test",
            default_region="us-central1",
            source_topic="trade-signals",
            message_id="msg-1",
            pubsub_published_at=now,
            firestore_writer=writer,
            replay=None,
        )
        self.assertTrue(r1.get("applied"))
        self.assertEqual(writer.upsert_calls, 1)

        # Redelivery with same messageId must be a noop and must not run side effects again.
        r2 = routed.handler(
            payload=payload,
            env="test",
            default_region="us-central1",
            source_topic="trade-signals",
            message_id="msg-1",
            pubsub_published_at=now,
            firestore_writer=writer,
            replay=None,
        )
        self.assertFalse(r2.get("applied"))
        self.assertEqual(r2.get("reason"), "duplicate_message_noop")
        self.assertEqual(writer.upsert_calls, 1)

    def test_replay_same_signal_id_does_not_reapply_with_new_message_id(self) -> None:
        payload = {"signal_id": "sig-1", "eventId": "evt-ignored"}
        dedupe_key = choose_trade_signal_dedupe_key(payload=payload, message_id="msg-aaa")
        self.assertEqual(dedupe_key, "sig-1")

        db = _FakeDB()
        replay = ReplayContext(run_id="run-1", consumer="cloudrun-consumer", topic="trade-signals")
        t = datetime.now(timezone.utc)

        ok1, why1 = ensure_event_not_applied(txn=db.transaction(), db=db, replay=replay, dedupe_key=dedupe_key, event_time=t, message_id="msg-aaa")
        self.assertTrue(ok1)
        self.assertEqual(why1, "not_applied_yet")

        # Different messageId but same signal_id => same dedupe_key => should be treated as already applied.
        ok2, why2 = ensure_event_not_applied(txn=db.transaction(), db=db, replay=replay, dedupe_key=dedupe_key, event_time=t, message_id="msg-bbb")
        self.assertFalse(ok2)
        self.assertEqual(why2, "already_applied_noop")


if __name__ == "__main__":
    unittest.main()

