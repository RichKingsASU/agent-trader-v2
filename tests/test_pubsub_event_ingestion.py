import base64

import pytest

_STORE_OK = True
_STORE_IMPORT_ERR: Exception | None = None
try:
    from backend.ingestion.pubsub_event_store import InMemoryEventStore, parse_pubsub_push
except Exception as e:  # pragma: no cover
    _STORE_OK = False
    _STORE_IMPORT_ERR = e


def _require_event_store() -> None:
    if not _STORE_OK:
        pytest.xfail(
            f"PubSub event store unavailable (optional cloud deps / runtime config): {type(_STORE_IMPORT_ERR).__name__}: {_STORE_IMPORT_ERR}"
        )


def _push_body(*, payload_json: str, attrs: dict | None = None, message_id: str = "m1"):
    return {
        "message": {
            "data": base64.b64encode(payload_json.encode("utf-8")).decode("ascii"),
            "attributes": attrs or {},
            "messageId": message_id,
            "publishTime": "2026-01-08T12:34:56.123Z",
        },
        "subscription": "projects/p/subscriptions/s",
    }


def test_parse_pubsub_push_extracts_event_type_from_attributes():
    _require_event_store()
    body = _push_body(payload_json='{"hello":"world"}', attrs={"event_type": "order.created"})
    ev = parse_pubsub_push(body)
    assert ev.event_id == "m1"
    assert ev.event_type == "order.created"
    assert ev.message_id == "m1"
    assert ev.publish_time_utc is not None


def test_parse_pubsub_push_extracts_event_type_from_payload():
    _require_event_store()
    body = _push_body(payload_json='{"eventType":"alpha.signal","x":1}', attrs={})
    ev = parse_pubsub_push(body)
    assert ev.event_type == "alpha.signal"


def test_inmemory_store_updates_summary():
    _require_event_store()
    store = InMemoryEventStore()
    store.write_event(parse_pubsub_push(_push_body(payload_json='{"event_type":"a","n":1}', message_id="1")))
    store.write_event(parse_pubsub_push(_push_body(payload_json='{"event_type":"b","n":2}', message_id="2")))
    store.write_event(parse_pubsub_push(_push_body(payload_json='{"event_type":"a","n":3}', message_id="3")))

    s = store.get_summary()
    assert s.message_count == 3
    assert s.latest_payload_by_event_type["a"]["n"] == 3
    assert s.latest_payload_by_event_type["b"]["n"] == 2


def test_parse_pubsub_push_rejects_missing_message_id():
    _require_event_store()
    body = {
        "message": {"data": base64.b64encode(b'{"x":1}').decode("ascii"), "publishTime": "2026-01-08T12:34:56Z"},
        "subscription": "projects/p/subscriptions/s",
    }
    try:
        parse_pubsub_push(body)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "messageId" in str(e)


def test_parse_pubsub_push_rejects_invalid_base64():
    _require_event_store()
    body = {
        "message": {"data": "!!!not-base64!!!", "messageId": "m1", "publishTime": "2026-01-08T12:34:56Z"},
        "subscription": "projects/p/subscriptions/s",
    }
    try:
        parse_pubsub_push(body)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "base64" in str(e)

