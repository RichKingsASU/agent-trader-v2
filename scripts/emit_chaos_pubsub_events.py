#!/usr/bin/env python3
"""
Emit valid + chaos Pub/Sub push test events to exercise consumers.

Targets the Cloud Run Pub/Sub push format used by `cloudrun_consumer/main.py`:
POST /pubsub/push with JSON body:
{
  "message": {
    "data": "base64(JSON)",
    "messageId": "...",
    "publishTime": "RFC3339",
    "attributes": {"topic": "..."}
  },
  "subscription": "projects/.../subscriptions/..."
}
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    # RFC3339-ish with Z suffix
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _b64_json(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _http_post_json(url: str, body: Any, *, timeout_s: float = 10.0) -> Tuple[int, str]:
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 200))
            resp_body = resp.read().decode("utf-8", errors="replace")
            return status, resp_body
    except urllib.error.HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        try:
            resp_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            resp_body = str(e)
        return status, resp_body


def _make_push_envelope(
    *,
    payload: Any,
    message_id: Optional[str],
    publish_time: Optional[str],
    attributes: Optional[Dict[str, str]] = None,
    subscription: Optional[str] = None,
    data_override: Optional[str] = None,
) -> Dict[str, Any]:
    msg: Dict[str, Any] = {}
    if message_id is not None:
        msg["messageId"] = message_id
    if publish_time is not None:
        msg["publishTime"] = publish_time
    msg["attributes"] = attributes or {}

    if data_override is not None:
        msg["data"] = data_override
    else:
        msg["data"] = _b64_json(payload)

    env: Dict[str, Any] = {"message": msg}
    if subscription is not None:
        env["subscription"] = subscription
    return env


def _valid_payload_for_topic(topic: str, *, now_iso: str, idx: int) -> Dict[str, Any]:
    # These are intentionally "loose" payloads: the consumer stores most fields verbatim under `data`.
    if topic == "market-ticks":
        return {
            "eventId": f"tick-{idx}-{uuid.uuid4().hex[:8]}",
            "symbol": "AAPL",
            "producedAt": now_iso,
            "price": 123.45,
            "size": 100,
        }
    if topic == "market-bars-1m":
        return {
            "eventId": f"bar-{idx}-{uuid.uuid4().hex[:8]}",
            "symbol": "AAPL",
            "timeframe": "1m",
            "producedAt": now_iso,
            "start": now_iso,
            "end": now_iso,
            "o": 123.0,
            "h": 124.0,
            "l": 122.5,
            "c": 123.7,
            "v": 123456,
        }
    if topic == "trade-signals":
        return {
            "eventId": f"signal-{idx}-{uuid.uuid4().hex[:8]}",
            "symbol": "AAPL",
            "strategy": "delta-momentum",
            "action": "BUY",
            "producedAt": now_iso,
            "confidence": 0.73,
        }
    raise ValueError(f"unsupported_topic:{topic}")


def _valid_system_event_payload(*, now_iso: str, idx: int) -> Dict[str, Any]:
    # Router: payload must contain "service" (non-empty string) and "timestamp" (present).
    return {
        "service": f"chaos-svc-{idx}",
        "timestamp": now_iso,
        "severity": "INFO",
        "version": "chaos-test",
        "region": "us-central1",
    }


def build_scenario(
    scenario: str,
    *,
    topic: str,
    subscription: str,
    idx: int,
    message_id: str,
    now_iso: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (scenario_label, pubsub_push_envelope).
    """
    if scenario == "valid_system_event":
        payload = _valid_system_event_payload(now_iso=now_iso, idx=idx)
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={},  # topic inferred from SYSTEM_EVENTS_TOPIC env var
            subscription=subscription,
        )
        return scenario, env

    if scenario == "valid_topic_event":
        payload = _valid_payload_for_topic(topic, now_iso=now_iso, idx=idx)
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
        )
        return f"{scenario}:{topic}", env

    # ---- Envelope-level chaos (exercise FastAPI /pubsub/push validation paths) ----
    if scenario == "missing_messageId":
        payload = _valid_payload_for_topic(topic, now_iso=now_iso, idx=idx)
        env = _make_push_envelope(
            payload=payload,
            message_id=None,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
        )
        return scenario, env

    if scenario == "missing_data":
        env = {"message": {"messageId": message_id, "publishTime": now_iso, "attributes": {"topic": topic}}, "subscription": subscription}
        return scenario, env

    if scenario == "invalid_base64":
        payload = _valid_payload_for_topic(topic, now_iso=now_iso, idx=idx)
        _ = payload
        env = _make_push_envelope(
            payload={"ignored": True},
            message_id=message_id,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
            data_override="!!!this-is-not-base64!!!",
        )
        return scenario, env

    if scenario == "invalid_payload_json":
        # base64 of a non-JSON string
        data_override = base64.b64encode(b"not json").decode("ascii")
        env = _make_push_envelope(
            payload={"ignored": True},
            message_id=message_id,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
            data_override=data_override,
        )
        return scenario, env

    if scenario == "payload_not_object":
        # base64 of JSON array => consumer returns 400 payload_not_object
        env = _make_push_envelope(
            payload=[{"a": 1}],
            message_id=message_id,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
        )
        return scenario, env

    # ---- Routing-level chaos (exercise schema_router + handler validation) ----
    if scenario == "unroutable_payload":
        payload = {"hello": "world", "timestamp": now_iso}  # has timestamp but not service; no topic => unroutable
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={},  # no topic
            subscription=subscription,
        )
        return scenario, env

    if scenario == "system_event_blank_service":
        payload = _valid_system_event_payload(now_iso=now_iso, idx=idx)
        payload["service"] = "   "  # truthy => routes, but handler strips => ValueError("missing_service")
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={},
            subscription=subscription,
        )
        return scenario, env

    if scenario == "system_event_invalid_producedAt":
        payload = _valid_system_event_payload(now_iso=now_iso, idx=idx)
        payload["producedAt"] = "not-a-timestamp"
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={},
            subscription=subscription,
        )
        return scenario, env

    # ---- Old schema / legacy shapes (valid JSON, but not the "current" consumer shape) ----
    if scenario == "old_schema_agent_envelope_wrapped":
        # Old agent envelope: the actual system fields are nested under payload, not at the top-level.
        # Consumer should reject as unroutable (400) rather than 500.
        payload = {
            "event_type": "system.health.v0",
            "agent_name": "legacy-agent",
            "git_sha": "deadbeef",
            "ts": now_iso,
            "trace_id": uuid.uuid4().hex,
            "payload": _valid_system_event_payload(now_iso=now_iso, idx=idx),
        }
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={},  # no topic; also won't match system_events router
            subscription=subscription,
        )
        return scenario, env

    if scenario == "old_schema_pubsub_event_wrapped":
        # PubSubEvent envelope: payload nested. With topic routing, consumer will accept and store it,
        # but fields like `symbol` may be missing at top-level (exercise schema flexibility).
        payload = {
            "eventType": "market.tick",
            "schemaVersion": 1,
            "producedAt": now_iso,
            "source": {"kind": "service", "name": "legacy-producer"},
            "payload": _valid_payload_for_topic(topic, now_iso=now_iso, idx=idx),
        }
        env = _make_push_envelope(
            payload=payload,
            message_id=message_id,
            publish_time=now_iso,
            attributes={"topic": topic},
            subscription=subscription,
        )
        return f"{scenario}:{topic}", env

    raise ValueError(f"unknown_scenario:{scenario}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit valid + chaos Pub/Sub push envelopes (print or POST).")
    parser.add_argument("--url", default="http://localhost:8080/pubsub/push", help="Consumer endpoint URL.")
    parser.add_argument(
        "--scenario",
        default="valid_topic_event",
        choices=[
            "valid_system_event",
            "valid_topic_event",
            "missing_messageId",
            "missing_data",
            "invalid_base64",
            "invalid_payload_json",
            "payload_not_object",
            "unroutable_payload",
            "system_event_blank_service",
            "system_event_invalid_producedAt",
            "old_schema_agent_envelope_wrapped",
            "old_schema_pubsub_event_wrapped",
        ],
        help="What to emit.",
    )
    parser.add_argument(
        "--topic",
        default="market-ticks",
        choices=["market-ticks", "market-bars-1m", "trade-signals"],
        help="Topic for topic-routed scenarios.",
    )
    parser.add_argument(
        "--subscription",
        default="projects/local/subscriptions/chaos",
        help="Subscription string for the Pub/Sub push envelope.",
    )
    parser.add_argument("--count", type=int, default=1, help="How many events to emit.")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep between sends (ms).")
    parser.add_argument("--dry-run", action="store_true", help="Print envelopes to stdout (no HTTP).")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON (dry-run only).")
    parser.add_argument("--timeout-s", type=float, default=10.0, help="HTTP timeout seconds.")
    args = parser.parse_args(argv)

    for i in range(args.count):
        now_iso = _utc_now_iso()
        message_id = f"chaos-{uuid.uuid4().hex}"
        label, env = build_scenario(
            args.scenario,
            topic=args.topic,
            subscription=args.subscription,
            idx=i,
            message_id=message_id,
            now_iso=now_iso,
        )

        if args.dry_run:
            if args.pretty:
                print(json.dumps(env, indent=2, ensure_ascii=False))
            else:
                print(json.dumps(env, separators=(",", ":"), ensure_ascii=False))
        else:
            status, resp_body = _http_post_json(args.url, env, timeout_s=args.timeout_s)
            # Keep output one-line per event for easy grepping in CI logs.
            out = {
                "scenario": label,
                "status": status,
                "messageId": message_id,
                "topic": args.topic,
                "ts": now_iso,
                "response": resp_body[:2000],  # cap noisy error payloads
            }
            print(json.dumps(out, separators=(",", ":"), ensure_ascii=False))

        if args.sleep_ms > 0 and i < args.count - 1:
            time.sleep(max(0.0, float(args.sleep_ms) / 1000.0))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

