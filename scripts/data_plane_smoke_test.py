#!/usr/bin/env python3
"""
End-to-end data plane smoke test:
  ingestor (publisher) -> Pub/Sub -> consumer -> Firestore

CI mode:
  - Uses Pub/Sub + Firestore emulators (expected to be started by wrapper script / CI).
  - Boots `cloudrun_consumer` locally (uvicorn), captures stdout logs.
  - Publishes a `system-events` message via `backend.messaging.publisher.PubSubPublisher`.
  - Asserts Firestore `ops_services/{serviceId}` updated AND structured logs emitted.

Staging mode:
  - Publishes to real Pub/Sub topic.
  - Polls real Firestore for the materialized doc update.
  - Optionally queries Cloud Logging for the expected structured log line.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name)
    if v is None or not str(v).strip():
        if default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return str(default)
    return str(v).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "t", "yes", "y", "on"}


def _sleep_poll_deadline(deadline_s: float, *, interval_s: float = 0.25) -> None:
    now = time.monotonic()
    remaining = max(0.0, deadline_s - now)
    time.sleep(min(interval_s, remaining))


def _http_get_ok(url: str, *, timeout_s: float = 2.0) -> bool:
    # stdlib-only (avoid requests dependency)
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310 (no user input)
            return 200 <= int(getattr(resp, "status", 0) or 0) < 300
    except Exception:
        return False


def _firestore_client(*, project_id: str):
    from google.cloud import firestore  # type: ignore

    # Firestore emulator is selected via FIRESTORE_EMULATOR_HOST env var.
    return firestore.Client(project=project_id)


def _pubsub_clients(*, project_id: str):
    from google.cloud import pubsub_v1  # type: ignore

    pub = pubsub_v1.PublisherClient()
    sub = pubsub_v1.SubscriberClient()
    return pub, sub


def _pubsub_ensure_topic_and_subscription(
    *,
    project_id: str,
    topic_id: str,
    subscription_id: str,
    push_endpoint: Optional[str],
) -> tuple[str, str]:
    pub, sub = _pubsub_clients(project_id=project_id)
    topic_path = pub.topic_path(project_id, topic_id)
    sub_path = sub.subscription_path(project_id, subscription_id)

    try:
        pub.create_topic(request={"name": topic_path})
    except Exception:
        # Emulator + real both raise AlreadyExists for existing topics; ignore.
        pass

    try:
        req: dict[str, Any] = {"name": sub_path, "topic": topic_path, "ack_deadline_seconds": 30}
        if push_endpoint:
            # Pub/Sub emulator support for push varies; this is best-effort and the
            # test can fall back to pull-forwarding if no delivery occurs.
            req["push_config"] = {"push_endpoint": str(push_endpoint)}
        sub.create_subscription(request=req)
    except Exception:
        # Already exists (or emulator limitation); ignore and continue.
        pass

    return topic_path, sub_path


def _publish_system_event_via_ingestor_lib(
    *,
    project_id: str,
    topic_id: str,
    service_id: str,
    env: str,
    region: str,
    validate_credentials: bool,
) -> str:
    # Use the same publisher wrapper ingestors use.
    from backend.ingestion.publisher import PubSubPublisher  # type: ignore

    payload = {
        "service": service_id,
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "severity": "INFO",
        "env": env,
        "region": region,
        "version": os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or "smoke",
    }

    pub = PubSubPublisher(
        project_id=project_id,
        topic_id=topic_id,
        agent_name="data-plane-smoke-test",
        git_sha=os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        validate_credentials=bool(validate_credentials),
    )
    try:
        # Consumer routes system events by payload shape, not by event_type.
        message_id = pub.publish_event(event_type="system.event", payload=payload)
        return str(message_id)
    finally:
        try:
            pub.close()
        except Exception:
            pass


def _pull_and_forward_once(
    *,
    project_id: str,
    subscription_path: str,
    consumer_push_url: str,
    timeout_s: float,
    topic_hint: str,
) -> Optional[str]:
    """
    Fallback delivery path for CI when Pub/Sub emulator push is unavailable:
      pull() one message and POST a Cloud Run Pub/Sub push envelope to the consumer.
    """
    from google.cloud import pubsub_v1  # type: ignore

    sub = pubsub_v1.SubscriberClient()
    deadline = time.monotonic() + max(0.1, float(timeout_s))

    import urllib.request

    while time.monotonic() < deadline:
        resp = sub.pull(
            request={
                "subscription": subscription_path,
                "max_messages": 1,
            },
            timeout=5,
        )
        if not resp or not getattr(resp, "received_messages", None):
            _sleep_poll_deadline(deadline, interval_s=0.25)
            continue

        rm = resp.received_messages[0]
        msg = rm.message
        mid = str(msg.message_id)
        publish_time = msg.publish_time.ToDatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        body = {
            "message": {
                # Pub/Sub push format uses base64-encoded data.
                "data": base64.b64encode(bytes(msg.data or b"")).decode("ascii"),
                "messageId": mid,
                "publishTime": publish_time,
                "attributes": {**(dict(msg.attributes) if msg.attributes else {}), "topic": topic_hint},
            },
            "subscription": f"projects/{project_id}/subscriptions/{subscription_path.split('/')[-1]}",
        }

        req = urllib.request.Request(  # noqa: S310 (no user input)
            consumer_push_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as http_resp:  # noqa: S310 (no user input)
            _ = http_resp.read()

        # Ack only after successful forward.
        sub.acknowledge(request={"subscription": subscription_path, "ack_ids": [rm.ack_id]})
        return mid

    return None


@dataclass(frozen=True)
class LogMatch:
    event_type: str
    message_id: str
    line: dict[str, Any]


def _wait_for_consumer_log(
    *,
    log_path: str,
    message_id: str,
    timeout_s: float,
) -> LogMatch:
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    last_err: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if str(obj.get("event_type") or "") != "materialize.ok":
                        continue
                    if str(obj.get("messageId") or "") != str(message_id):
                        continue
                    return LogMatch(event_type="materialize.ok", message_id=str(message_id), line=obj)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for consumer log materialize.ok for messageId={message_id} (last_err={last_err})")


def _wait_for_firestore_doc(
    *,
    project_id: str,
    service_id: str,
    expected_message_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    db = _firestore_client(project_id=project_id)
    ref = db.collection("ops_services").document(service_id)
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        snap = ref.get()
        if getattr(snap, "exists", False):
            d = snap.to_dict() or {}
            src = d.get("source") if isinstance(d, dict) else None
            src_mid = None
            if isinstance(src, dict):
                src_mid = src.get("messageId") or src.get("message_id")
            if str(src_mid or "") == str(expected_message_id):
                return d
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for Firestore ops_services/{service_id} to reflect messageId={expected_message_id}")


def _maybe_assert_cloud_logging(
    *,
    project_id: str,
    message_id: str,
    timeout_s: float,
) -> None:
    """
    Best-effort staging-only log assertion via Cloud Logging API.

    Requires google-cloud-logging and credentials with logs.viewer.
    """
    try:
        from google.cloud import logging as gcp_logging  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "google-cloud-logging is required for staging log assertions. "
            "Install it (pip install google-cloud-logging) or run CI mode."
        ) from e

    client = gcp_logging.Client(project=project_id)
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    # Query a tight time window (last ~10 minutes) and a tight predicate on messageId.
    start = (_utc_now() - timedelta(minutes=10)).isoformat()
    flt = (
        'resource.type="cloud_run_revision" '
        f'AND jsonPayload.event_type="materialize.ok" '
        f'AND jsonPayload.messageId="{message_id}" '
        f'AND timestamp>="{start}"'
    )

    while time.monotonic() < deadline:
        entries = list(client.list_entries(filter_=flt, page_size=5))
        if entries:
            return
        time.sleep(2.0)
    raise RuntimeError(f"Timed out waiting for Cloud Logging entry materialize.ok for messageId={message_id}")


def _start_consumer_local(*, port: int, log_path: str, env: dict[str, str]) -> subprocess.Popen[str]:
    consumer_dir = os.path.join(os.getcwd(), "cloudrun_consumer")
    out = open(log_path, "w", encoding="utf-8")  # noqa: P201 - closed by caller
    # Use uvicorn module from the active environment.
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning", "--access-log", "false"],
        cwd=consumer_dir,
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["ci", "staging"], default=os.getenv("SMOKE_MODE") or "ci")
    ap.add_argument("--topic", default=os.getenv("SYSTEM_EVENTS_TOPIC") or "system-events")
    ap.add_argument("--service-id", default=os.getenv("SMOKE_SERVICE_ID") or f"smoke-{int(time.time())}")
    ap.add_argument("--timeout-s", type=float, default=float(os.getenv("SMOKE_TIMEOUT_S") or "90"))
    ap.add_argument("--consumer-port", type=int, default=int(os.getenv("SMOKE_CONSUMER_PORT") or "18081"))
    ap.add_argument("--assert-cloud-logging", action="store_true", default=_bool_env("SMOKE_ASSERT_CLOUD_LOGGING", False))
    args = ap.parse_args()

    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT") or ""
    if not project_id.strip():
        # CI default
        project_id = "smoke-test"
    project_id = project_id.strip()

    env = os.getenv("ENV") or ("ci" if args.mode == "ci" else "staging")
    default_region = os.getenv("DEFAULT_REGION") or "us-central1"

    # Emulator detection affects publisher credential validation.
    using_pubsub_emulator = bool((os.getenv("PUBSUB_EMULATOR_HOST") or "").strip())
    validate_credentials = not using_pubsub_emulator

    consumer_proc: Optional[subprocess.Popen[str]] = None
    consumer_log_path = os.path.join(os.getcwd(), f".smoke_consumer_{os.getpid()}.log")

    try:
        subscription_id = f"system-events-smoke-{os.getpid()}"

        if args.mode == "ci":
            # Boot consumer locally pointed at Firestore emulator.
            consumer_env = dict(os.environ)
            consumer_env.setdefault("GCP_PROJECT", project_id)
            consumer_env.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
            consumer_env.setdefault("ENV", env)
            consumer_env.setdefault("DEFAULT_REGION", default_region)
            consumer_env.setdefault("SYSTEM_EVENTS_TOPIC", args.topic)
            consumer_env.setdefault("INGEST_FLAG_SECRET_ID", "dummy")

            consumer_proc = _start_consumer_local(port=args.consumer_port, log_path=consumer_log_path, env=consumer_env)

            ready_url = f"http://127.0.0.1:{args.consumer_port}/readyz"
            deadline = time.monotonic() + max(5.0, float(args.timeout_s))
            while time.monotonic() < deadline and consumer_proc.poll() is None:
                if _http_get_ok(ready_url, timeout_s=1.0):
                    break
                time.sleep(0.25)
            if consumer_proc.poll() is not None:
                raise RuntimeError("consumer exited early; see consumer log for details")
            if not _http_get_ok(ready_url, timeout_s=1.0):
                raise RuntimeError("consumer did not become ready in time")

            # Ensure topic/subscription exist in Pub/Sub emulator; best-effort push config.
            push_url = f"http://127.0.0.1:{args.consumer_port}/pubsub/push"
            _, sub_path = _pubsub_ensure_topic_and_subscription(
                project_id=project_id,
                topic_id=args.topic,
                subscription_id=subscription_id,
                push_endpoint=push_url,
            )
        else:
            # Staging assumes infra already exists (topic + push subscription to consumer).
            sub_path = ""

        # Publish a system event via the ingestor publisher library.
        message_id = _publish_system_event_via_ingestor_lib(
            project_id=project_id,
            topic_id=args.topic,
            service_id=args.service_id,
            env=env,
            region=default_region,
            validate_credentials=validate_credentials,
        )

        # If we're in CI and push delivery isn't working in the emulator, pull+forward once.
        if args.mode == "ci":
            # Wait briefly for Firestore update via real push delivery; if not, fallback.
            try:
                _wait_for_firestore_doc(
                    project_id=project_id,
                    service_id=args.service_id,
                    expected_message_id=message_id,
                    timeout_s=min(20.0, float(args.timeout_s)),
                )
            except Exception:
                forwarded = _pull_and_forward_once(
                    project_id=project_id,
                    subscription_path=sub_path,
                    consumer_push_url=f"http://127.0.0.1:{args.consumer_port}/pubsub/push",
                    timeout_s=min(30.0, float(args.timeout_s)),
                    topic_hint=args.topic,
                )
                if forwarded and str(forwarded) != str(message_id):
                    # Emulator publish messageId should match, but be defensive.
                    message_id = str(forwarded)

        # Firestore assertion (emulator in CI; real in staging).
        doc = _wait_for_firestore_doc(
            project_id=project_id,
            service_id=args.service_id,
            expected_message_id=message_id,
            timeout_s=float(args.timeout_s),
        )

        # Structured log assertion.
        if args.mode == "ci":
            _ = _wait_for_consumer_log(log_path=consumer_log_path, message_id=message_id, timeout_s=float(args.timeout_s))
        elif args.assert_cloud_logging:
            _maybe_assert_cloud_logging(project_id=project_id, message_id=message_id, timeout_s=float(args.timeout_s))

        # Human-readable success line (CI)
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "mode": args.mode,
                    "topic": args.topic,
                    "project": project_id,
                    "serviceId": args.service_id,
                    "messageId": message_id,
                    "firestoreDoc": {"collection": "ops_services", "id": args.service_id},
                    "observed": {"env": doc.get("env"), "status": doc.get("status")},
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0
    finally:
        if consumer_proc is not None and consumer_proc.poll() is None:
            try:
                consumer_proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
            try:
                consumer_proc.wait(timeout=10)
            except Exception:
                try:
                    consumer_proc.kill()
                except Exception:
                    pass
        # Keep logs for debugging on failure; CI wrapper can clean them up on success.


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)

