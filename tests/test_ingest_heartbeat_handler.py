from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from backend.ingestion.ingest_heartbeat_handler import extract_subscription_id, parse_ingest_heartbeat
from backend.ingestion.pubsub_event_store import parse_pubsub_push


def _push_body(*, payload_obj: dict, attrs: dict | None = None, message_id: str = "m1", subscription_id: str = "ingest-heartbeat"):
    payload_json = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
    return {
        "message": {
            "data": base64.b64encode(payload_json.encode("utf-8")).decode("ascii"),
            "attributes": attrs or {},
            "messageId": message_id,
            "publishTime": "2026-01-08T12:34:56.123Z",
        },
        "subscription": f"projects/p/subscriptions/{subscription_id}",
    }


def test_extract_subscription_id():
    assert extract_subscription_id("projects/p/subscriptions/ingest-heartbeat") == "ingest-heartbeat"
    assert extract_subscription_id("ingest-heartbeat") == "ingest-heartbeat"
    assert extract_subscription_id(None) is None


def test_parse_ingest_heartbeat_from_envelope():
    body = _push_body(
        payload_obj={
            "event_type": "ingest.heartbeat",
            "agent_name": "market_ingest",
            "git_sha": "abc",
            "ts": "2026-01-08T12:00:00Z",
            "payload": {"status": "running", "pipeline_id": "market_ingest", "tenant_id": "t1"},
            "trace_id": "trace123",
        },
        attrs={"event_type": "ingest.heartbeat"},
        message_id="mid-1",
    )
    ev = parse_pubsub_push(body)
    hb = parse_ingest_heartbeat(ev)
    assert hb is not None
    assert hb.pipeline_id == "market_ingest"
    assert hb.status == "running"
    assert hb.tenant_id == "t1"
    assert hb.agent_name == "market_ingest"
    assert hb.git_sha == "abc"
    assert hb.trace_id == "trace123"
    assert hb.event_ts_utc == datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_ingest_heartbeat_from_inner_payload_fallbacks_pipeline_id():
    body = _push_body(
        payload_obj={"status": "ok", "service": "pipelineA", "ts": "2026-01-08T12:00:00Z"},
        attrs={"event_type": "ingest.heartbeat"},
        message_id="mid-2",
    )
    ev = parse_pubsub_push(body)
    hb = parse_ingest_heartbeat(ev)
    assert hb is not None
    assert hb.pipeline_id == "pipelineA"
    assert hb.status == "ok"

