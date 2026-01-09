from __future__ import annotations

import argparse
import base64
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _b64_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _make_system_event_payload(*, service: str, env: str, region: str) -> Dict[str, Any]:
    return {
        "service": service,
        "severity": "INFO",
        "timestamp": _now_rfc3339(),
        "version": "loadtest",
        "env": env,
        "region": region,
        "producedAt": _now_rfc3339(),
    }


def _make_push_envelope(
    *,
    topic: str,
    subscription: str,
    message_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "message": {
            "data": _b64_json(payload),
            "messageId": message_id,
            "publishTime": _now_rfc3339(),
            "attributes": {"topic": topic},
        },
        "subscription": subscription,
    }


def _post_json(url: str, body: Dict[str, Any], timeout_s: float) -> Tuple[int, float, str]:
    data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            _ = resp.read()  # ensure connection reuse
            elapsed = time.perf_counter() - started
            return status, elapsed, ""
    except urllib.error.HTTPError as e:
        # HTTPError is also a response; capture status + body for debugging.
        try:
            _ = e.read()
        except Exception:
            pass
        elapsed = time.perf_counter() - started
        return int(e.code), elapsed, f"http_error:{e.code}"
    except Exception as e:
        elapsed = time.perf_counter() - started
        return 0, elapsed, f"exception:{e.__class__.__name__}:{e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Load test Pub/Sub push endpoint (Cloud Run consumer).")
    ap.add_argument("--url", default="http://localhost:8080/pubsub/push")
    ap.add_argument("--requests", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--timeout-s", type=float, default=15.0)
    ap.add_argument("--topic", default="system.events")
    ap.add_argument("--subscription", default="projects/local/subscriptions/loadtest")
    ap.add_argument("--service", default="loadtest-service")
    ap.add_argument("--env", default="local")
    ap.add_argument("--region", default="local")
    args = ap.parse_args()

    total = max(1, int(args.requests))
    conc = max(1, int(args.concurrency))
    timeout_s = max(0.1, float(getattr(args, "timeout_s")))

    lock = threading.Lock()
    status_counts: Dict[int, int] = {}
    errors: Dict[str, int] = {}
    latencies: list[float] = []

    def _one(i: int) -> Tuple[int, float, str]:
        msg_id = f"loadtest-{uuid.uuid4()}"
        payload = _make_system_event_payload(service=args.service, env=args.env, region=args.region)
        envlp = _make_push_envelope(topic=args.topic, subscription=args.subscription, message_id=msg_id, payload=payload)
        return _post_json(args.url, envlp, timeout_s=timeout_s)

    started_all = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futures = [ex.submit(_one, i) for i in range(total)]
        for fut in as_completed(futures):
            status, elapsed, err = fut.result()
            with lock:
                status_counts[status] = status_counts.get(status, 0) + 1
                latencies.append(elapsed)
                if err:
                    errors[err] = errors.get(err, 0) + 1

    elapsed_all = time.perf_counter() - started_all
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[int(0.50 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0
    p95 = latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0
    p99 = latencies_sorted[int(0.99 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0

    print("== load test summary ==")
    print(f"url={args.url}")
    print(f"requests={total} concurrency={conc} elapsed_s={elapsed_all:.3f} approx_rps={total/elapsed_all:.1f}")
    print(f"latency_s: mean={statistics.mean(latencies):.4f} p50={p50:.4f} p95={p95:.4f} p99={p99:.4f} max={max(latencies):.4f}")
    print("status_counts:")
    for code in sorted(status_counts.keys()):
        print(f"  {code}: {status_counts[code]}")
    if errors:
        print("errors (top 10):")
        for k, v in sorted(errors.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            print(f"  {k}: {v}")

    # Non-zero exit if we see transport errors.
    return 1 if status_counts.get(0, 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

