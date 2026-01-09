from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from cloudrun_consumer.firestore_writer import FirestoreWriter, SourceInfo
from cloudrun_consumer.replay_support import ReplayContext


class _Snap:
    def __init__(self, *, exists: bool, data: Optional[dict[str, Any]] = None) -> None:
        self.exists = bool(exists)
        self._data = deepcopy(data) if isinstance(data, dict) else None

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data) if isinstance(self._data, dict) else {}


@dataclass(frozen=True)
class _DocRef:
    _db: "_FakeDB"
    _col: str
    _doc_id: str

    def get(self, *, transaction: Any = None) -> _Snap:  # noqa: ARG002
        key = (self._col, self._doc_id)
        if key not in self._db._store:
            return _Snap(exists=False)
        return _Snap(exists=True, data=self._db._store[key])


@dataclass(frozen=True)
class _ColRef:
    _db: "_FakeDB"
    _name: str

    def document(self, doc_id: str) -> _DocRef:
        return _DocRef(self._db, self._name, str(doc_id))


class _Txn:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def create(self, ref: _DocRef, doc: dict[str, Any]) -> None:
        key = (ref._col, ref._doc_id)
        if key in self._db._store:
            raise RuntimeError("AlreadyExists")
        self._db._store[key] = deepcopy(doc)

    def set(self, ref: _DocRef, doc: dict[str, Any], merge: bool = False) -> None:
        key = (ref._col, ref._doc_id)
        if not merge or key not in self._db._store:
            self._db._store[key] = deepcopy(doc)
            return
        existing = self._db._store[key]
        assert isinstance(existing, dict)
        existing.update(deepcopy(doc))
        self._db._store[key] = existing


class _FakeDB:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}

    def collection(self, name: str) -> _ColRef:
        return _ColRef(self, str(name))

    def transaction(self) -> _Txn:
        return _Txn(self)

    def get_doc(self, *, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        return deepcopy(self._store.get((str(collection), str(doc_id))))


class _FakeFirestoreMod:
    # Use a stable sentinel so dict equality checks are meaningful.
    SERVER_TIMESTAMP = "__SERVER_TIMESTAMP__"

    @staticmethod
    def transactional(fn: Any) -> Any:
        def _wrapped(txn: Any) -> Any:
            return fn(txn)

        return _wrapped


def _writer() -> FirestoreWriter:
    w = FirestoreWriter.__new__(FirestoreWriter)
    w._db = _FakeDB()
    w._firestore = _FakeFirestoreMod()
    w._collection_prefix = ""
    return w


def _utc(y: int, m: int, d: int, hh: int, mm: int, ss: int) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def test_message_redelivery_noop_for_trade_signal() -> None:
    w = _writer()
    db: _FakeDB = w._db  # type: ignore[assignment]

    t = _utc(2026, 1, 9, 12, 0, 0)
    src = SourceInfo(topic="trade-signals", message_id="m1", published_at=t)

    applied1, why1 = w.upsert_trade_signal(
        doc_id="m1",
        event_id=None,
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry"},
        source=src,
        replay=None,
    )
    assert applied1 is True
    assert why1 == "applied"

    before = db.get_doc(collection="trade_signals", doc_id="m1")
    assert isinstance(before, dict)

    applied2, why2 = w.upsert_trade_signal(
        doc_id="m1",
        event_id=None,
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry"},
        source=src,
        replay=None,
    )
    assert applied2 is False
    assert why2 == "duplicate_message_noop"

    after = db.get_doc(collection="trade_signals", doc_id="m1")
    assert after == before

    # MessageId dedupe doc exists.
    assert db.get_doc(collection="ops_dedupe", doc_id="m1") is not None

    # Business-dedupe doc exists (hash is opaque; ensure the collection has exactly 1 entry).
    business = [k for k in db._store.keys() if k[0] == "ops_trade_signal_dedupe_business"]
    assert len(business) == 1


def test_replay_event_id_noop_for_trade_signal() -> None:
    w = _writer()
    db: _FakeDB = w._db  # type: ignore[assignment]

    t = _utc(2026, 1, 9, 12, 1, 0)
    replay = ReplayContext(run_id="r1", consumer="cloudrun_consumer", topic="trade-signals")

    applied1, why1 = w.upsert_trade_signal(
        doc_id="evt-1",
        event_id="evt-1",
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "evt-1"},
        source=SourceInfo(topic="trade-signals", message_id="m1", published_at=t),
        replay=replay,
    )
    assert applied1 is True
    assert why1 == "applied"

    before = db.get_doc(collection="trade_signals", doc_id="evt-1")
    assert isinstance(before, dict)

    applied2, why2 = w.upsert_trade_signal(
        doc_id="evt-1",
        event_id="evt-1",
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "evt-1"},
        source=SourceInfo(topic="trade-signals", message_id="m2", published_at=t),
        replay=replay,
    )
    assert applied2 is False
    assert why2 == "already_applied_noop"

    after = db.get_doc(collection="trade_signals", doc_id="evt-1")
    assert after == before


def test_out_of_order_event_time_noop() -> None:
    w = _writer()
    db: _FakeDB = w._db  # type: ignore[assignment]

    t_new = _utc(2026, 1, 9, 12, 2, 0)
    t_old = _utc(2026, 1, 9, 12, 1, 59)

    applied1, _ = w.upsert_trade_signal(
        doc_id="sig-1",
        event_id="sig-1",
        event_time=t_new,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "sig-1"},
        source=SourceInfo(topic="trade-signals", message_id="m1", published_at=t_new),
        replay=None,
    )
    assert applied1 is True

    before = db.get_doc(collection="trade_signals", doc_id="sig-1")
    assert isinstance(before, dict)

    applied2, why2 = w.upsert_trade_signal(
        doc_id="sig-1",
        event_id="sig-1",
        event_time=t_old,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "sig-1"},
        source=SourceInfo(topic="trade-signals", message_id="m2", published_at=t_old),
        replay=None,
    )
    assert applied2 is False
    assert why2 == "stale_event_ignored"

    after = db.get_doc(collection="trade_signals", doc_id="sig-1")
    assert after == before

    # In LWW NOOP path we do not write dedupe markers for the losing messageId.
    assert db.get_doc(collection="ops_dedupe", doc_id="m2") is None


def test_newer_event_time_applies() -> None:
    w = _writer()
    db: _FakeDB = w._db  # type: ignore[assignment]

    t_old = _utc(2026, 1, 9, 12, 3, 0)
    t_new = _utc(2026, 1, 9, 12, 3, 1)

    applied1, _ = w.upsert_trade_signal(
        doc_id="sig-2",
        event_id="sig-2",
        event_time=t_old,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "sig-2"},
        source=SourceInfo(topic="trade-signals", message_id="m1", published_at=t_old),
        replay=None,
    )
    assert applied1 is True

    applied2, why2 = w.upsert_trade_signal(
        doc_id="sig-2",
        event_id="sig-2",
        event_time=t_new,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data={"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry", "eventId": "sig-2"},
        source=SourceInfo(topic="trade-signals", message_id="m2", published_at=t_new),
        replay=None,
    )
    assert applied2 is True
    assert why2 == "applied"

    stored = db.get_doc(collection="trade_signals", doc_id="sig-2")
    assert isinstance(stored, dict)
    assert stored.get("eventTime") == t_new


def test_business_dedupe_noop_without_replay_context() -> None:
    """
    Two different Pub/Sub messages (different messageIds) can represent the same logical signal.
    Business-level dedupe must prevent duplicate trade_signals docs when replay context is absent.
    """
    w = _writer()
    db: _FakeDB = w._db  # type: ignore[assignment]

    t = _utc(2026, 1, 9, 12, 4, 0)
    payload = {"symbol": "AAPL", "strategyId": "s1", "action": "BUY", "signalType": "entry"}

    applied1, _ = w.upsert_trade_signal(
        doc_id="m1",  # simulate missing eventId -> docId derived from messageId
        event_id=None,
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data=dict(payload),
        source=SourceInfo(topic="trade-signals", message_id="m1", published_at=t),
        replay=None,
    )
    assert applied1 is True
    assert db.get_doc(collection="trade_signals", doc_id="m1") is not None

    applied2, why2 = w.upsert_trade_signal(
        doc_id="m2",  # different messageId -> would otherwise create a second doc
        event_id=None,
        event_time=t,
        produced_at=None,
        published_at=None,
        symbol="AAPL",
        strategy="s1",
        action="BUY",
        data=dict(payload),
        source=SourceInfo(topic="trade-signals", message_id="m2", published_at=t),
        replay=None,
    )
    assert applied2 is False
    assert why2 == "duplicate_business_noop"
    assert db.get_doc(collection="trade_signals", doc_id="m2") is None

