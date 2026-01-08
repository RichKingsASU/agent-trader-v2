#!/usr/bin/env bash
set -euo pipefail

# Pull a small sample from a Pub/Sub DLQ subscription for inspection.
#
# Safe-by-default:
# - does NOT ack messages unless --ack is provided
# - writes a JSONL sample file if --out is provided
#
# Requirements:
# - python3
# - Application Default Credentials (ADC) for Pub/Sub (or equivalent)
#
# Example:
#   ./scripts/dlq_pull_sample.sh \
#     --subscription "projects/<PROJECT>/subscriptions/<SUB>.dlq-sub" \
#     --limit 10 \
#     --out "audit_artifacts/dlq_sample_$(date -u +%Y%m%dT%H%M%SZ).jsonl"

usage() {
  cat <<'EOF'
Usage:
  dlq_pull_sample.sh --subscription <DLQ_SUBSCRIPTION> [--limit N] [--ack] [--out PATH] [--project PROJECT_ID]

Options:
  --subscription   Full Pub/Sub subscription path (or short id)
  --limit          Number of messages to pull (default: 10)
  --ack            Ack pulled messages (default: no ack)
  --out            Write JSONL sample to PATH (default: none)
  --project        GCP project id (required if --subscription is not a full path)

Output:
  - Prints a short summary per message to stdout.
  - If --out is provided, writes JSONL records including decoded payload (best-effort).
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

SUBSCRIPTION=""
LIMIT="10"
AUTO_ACK="0"
OUT_PATH=""
PROJECT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subscription)
      SUBSCRIPTION="${2:-}"; shift 2 ;;
    --limit)
      LIMIT="${2:-}"; shift 2 ;;
    --ack)
      AUTO_ACK="1"; shift ;;
    --out)
      OUT_PATH="${2:-}"; shift 2 ;;
    --project)
      PROJECT_ID="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${SUBSCRIPTION}" ]]; then
  echo "ERROR: --subscription is required" >&2
  usage
  exit 2
fi

require_cmd python3

python3 - <<'PY' "${SUBSCRIPTION}" "${LIMIT}" "${AUTO_ACK}" "${OUT_PATH}" "${PROJECT_ID}"
import base64
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from google.cloud import pubsub_v1

subscription_arg = sys.argv[1]
limit = int(sys.argv[2])
auto_ack = sys.argv[3] == "1"
out_path = sys.argv[4] if sys.argv[4] else ""
project_id = (sys.argv[5] or "").strip()

def as_full_subscription(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("projects/") and "/subscriptions/" in s:
        return s
    if not project_id:
        raise SystemExit("ERROR: provide a full subscription path or pass --project")
    return f"projects/{project_id}/subscriptions/{s}"

sub_path = as_full_subscription(subscription_arg)
subscriber = pubsub_v1.SubscriberClient()
resp = subscriber.pull(subscription=sub_path, max_messages=limit)
received = list(resp.received_messages or [])
if not received:
    print("No messages returned.")
    raise SystemExit(0)

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "client_secret",
}

def sanitize(v: Any) -> Any:
    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, vv in v.items():
            ks = str(k).lower()
            if ks in SENSITIVE_KEYS:
                out[str(k)] = "[redacted]"
            else:
                out[str(k)] = sanitize(vv)
        return out
    if isinstance(v, list):
        return [sanitize(x) for x in v[:50]]
    return v

rows = []
ack_ids = []
for rm in received:
    ack_id = rm.ack_id
    ack_ids.append(ack_id)
    m = rm.message
    message_id = (m.message_id or "").strip()
    publish_time_dt = m.publish_time.ToDatetime().replace(tzinfo=timezone.utc) if m.publish_time else datetime.now(timezone.utc)
    publish_time = publish_time_dt.isoformat()
    data_bytes = m.data or b""
    data_b64 = base64.b64encode(data_bytes).decode("ascii")
    attrs = dict(m.attributes or {})
    delivery_attempt = getattr(rm, "delivery_attempt", None)

    decoded_text = ""
    decoded_json = None
    decode_error = ""
    if data_bytes:
        try:
            decoded_text = data_bytes.decode("utf-8", errors="replace")
            try:
                decoded_json = json.loads(decoded_text)
            except Exception:
                decoded_json = None
        except Exception as e:
            decode_error = str(e)

    # Human summary (stdout)
    print(
        json.dumps(
            {
                "messageId": message_id,
                "publishTime": publish_time,
                "deliveryAttempt": delivery_attempt,
                "attributesKeys": sorted(list(attrs.keys()))[:30],
                "dataBytes": int(len(data_bytes)),
                "acked": False,  # this script cannot know; shown for readability
                "hasDecodeError": bool(decode_error),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )

    row = {
        "ackId": ack_id,
        "messageId": message_id,
        "publishTime": publish_time,
        "deliveryAttempt": delivery_attempt,
        "attributes": dict(attrs),
        "dataBase64": data_b64,
    }
    if decode_error:
        row["decodeError"] = decode_error
    if decoded_json is not None:
        row["payload"] = sanitize(decoded_json)
        row["payloadType"] = "json"
    elif decoded_text:
        # Keep bounded text to avoid huge sample artifacts.
        row["payloadTextSnippet"] = decoded_text[:24_000]
        row["payloadType"] = "text"

    rows.append(row)

if out_path:
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} message sample(s) to: {out_path}", file=sys.stderr)

if auto_ack:
    subscriber.acknowledge(subscription=sub_path, ack_ids=ack_ids)
    print(f"Acked {len(ack_ids)} message(s).", file=sys.stderr)
PY

