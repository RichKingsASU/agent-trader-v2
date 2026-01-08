#!/usr/bin/env bash
set -euo pipefail

# Idempotent replay from a Pub/Sub DLQ subscription back to a target topic.
#
# Safety properties:
# - Republishes the ORIGINAL message bytes + attributes back to a topic, so messages re-enter the
#   normal consumer pipeline (contract validation still applies).
# - Writes a Firestore "replay watermark" per DLQ message BEFORE ACKing, so reruns do not republish.
# - Only ACKs after publish success + watermark update.
#
# Requirements:
# - python3
# - Application Default Credentials (ADC) for Pub/Sub + Firestore with required permissions
#
# Example:
#   ./scripts/dlq_replay.sh \
#     --dlq-subscription "projects/<PROJECT>/subscriptions/<SUB>.dlq-sub" \
#     --target-topic "projects/<PROJECT>/topics/<ORIGINAL_TOPIC>" \
#     --run-id "dlq-replay-2026-01-08T000000Z" \
#     --batch-size 25 \
#     --max-messages 500 \
#     --qps 5 \
#     --yes

usage() {
  cat <<'EOF'
Usage:
  dlq_replay.sh --dlq-subscription <DLQ_SUB> --target-topic <TOPIC> [options]

Required:
  --dlq-subscription   DLQ subscription (full path recommended)
  --target-topic       Topic to republish messages to (full path recommended)

Safety / control:
  --yes                Required to perform publish+ack (prevents accidental runs)
  --dry-run            Do not publish, do not ack; only print what would happen
  --qps N              Publish rate limit (messages/sec). 0 = unlimited (default: 5)
  --batch-size N       Pull batch size per request (default: 25)
  --max-messages N     Stop after N messages (default: 0 = drain until empty)

Identity / auditing:
  --run-id ID          Replay run id used in Firestore watermarks (default: dlq-replay-<UTC timestamp>)
  --project PROJECT    GCP project id (required if topic/subscription are not full paths)

Firestore watermark config (optional):
  FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT   Project to write watermarks into
  FIRESTORE_DATABASE                           Firestore database (default: "(default)")
  FIRESTORE_COLLECTION_PREFIX                  Optional collection prefix (default: "")

What gets written:
  - `ops_replay_runs/{runId}` (merge=true) with run metadata
  - `ops_replay_events/<stable-id>` per DLQ message (create-once; then status updates)

Exit codes:
  0 success, 2 usage error, 3 missing dependencies, 4 runtime failure
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 3
  fi
}

DLQ_SUB=""
TARGET_TOPIC=""
PROJECT_ID=""
RUN_ID=""
DRY_RUN="0"
YES="0"
QPS="5"
BATCH_SIZE="25"
MAX_MESSAGES="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dlq-subscription)
      DLQ_SUB="${2:-}"; shift 2 ;;
    --target-topic)
      TARGET_TOPIC="${2:-}"; shift 2 ;;
    --project)
      PROJECT_ID="${2:-}"; shift 2 ;;
    --run-id)
      RUN_ID="${2:-}"; shift 2 ;;
    --dry-run)
      DRY_RUN="1"; shift ;;
    --yes)
      YES="1"; shift ;;
    --qps)
      QPS="${2:-}"; shift 2 ;;
    --batch-size)
      BATCH_SIZE="${2:-}"; shift 2 ;;
    --max-messages)
      MAX_MESSAGES="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${DLQ_SUB}" || -z "${TARGET_TOPIC}" ]]; then
  echo "ERROR: --dlq-subscription and --target-topic are required" >&2
  usage
  exit 2
fi

require_cmd python3

if [[ "${DRY_RUN}" != "1" && "${YES}" != "1" ]]; then
  echo "ERROR: refusing to run without --yes (or use --dry-run)" >&2
  exit 2
fi

if [[ -z "${RUN_ID}" ]]; then
  RUN_ID="dlq-replay-$(date -u +%Y%m%dT%H%M%SZ)"
fi

FIRESTORE_PROJECT_ID="${FIRESTORE_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-""}}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-"(default)"}"
FIRESTORE_COLLECTION_PREFIX="${FIRESTORE_COLLECTION_PREFIX:-""}"

if [[ "${DRY_RUN}" != "1" && -z "${FIRESTORE_PROJECT_ID}" ]]; then
  echo "ERROR: set FIRESTORE_PROJECT_ID or GOOGLE_CLOUD_PROJECT for watermark writes" >&2
  exit 4
fi

echo "== DLQ replay =="
echo "DLQ subscription : ${DLQ_SUB}"
echo "Target topic     : ${TARGET_TOPIC}"
echo "Run id           : ${RUN_ID}"
echo "Dry run          : ${DRY_RUN}"
echo "Rate limit (qps) : ${QPS}"
echo "Batch size       : ${BATCH_SIZE}"
echo "Max messages     : ${MAX_MESSAGES}"
echo "Project override : ${PROJECT_ID:-"(none)"}"
if [[ "${DRY_RUN}" != "1" ]]; then
  echo "Firestore project: ${FIRESTORE_PROJECT_ID}"
  echo "Firestore db     : ${FIRESTORE_DATABASE}"
  echo "FS prefix        : ${FIRESTORE_COLLECTION_PREFIX}"
fi
echo

export DLQ_SUB
export TARGET_TOPIC
export PROJECT_ID
export RUN_ID
export DRY_RUN
export QPS
export BATCH_SIZE
export MAX_MESSAGES
export FIRESTORE_PROJECT_ID
export FIRESTORE_DATABASE
export FIRESTORE_COLLECTION_PREFIX

python3 - <<'PY'
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

DLQ_SUB = os.environ["DLQ_SUB"]
TARGET_TOPIC = os.environ["TARGET_TOPIC"]
PROJECT_ID = (os.environ.get("PROJECT_ID") or "").strip()
RUN_ID = os.environ["RUN_ID"]
DRY_RUN = (os.environ.get("DRY_RUN") or "0") == "1"
QPS = float(os.environ.get("QPS") or "5")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE") or "25")
MAX_MESSAGES = int(os.environ.get("MAX_MESSAGES") or "0")

FIRESTORE_PROJECT_ID = (os.environ.get("FIRESTORE_PROJECT_ID") or "").strip()
FIRESTORE_DATABASE = (os.environ.get("FIRESTORE_DATABASE") or "(default)").strip()
PREFIX = (os.environ.get("FIRESTORE_COLLECTION_PREFIX") or "").strip()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def col(name: str) -> str:
    return f"{PREFIX}{name}" if PREFIX else name

def full_subscription_path(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("projects/") and "/subscriptions/" in s:
        return s
    if not PROJECT_ID:
        raise RuntimeError("subscription is not a full path; pass --project")
    return f"projects/{PROJECT_ID}/subscriptions/{s}"

def full_topic_path(t: str) -> str:
    t = (t or "").strip()
    if t.startswith("projects/") and "/topics/" in t:
        return t
    if not PROJECT_ID:
        raise RuntimeError("topic is not a full path; pass --project")
    return f"projects/{PROJECT_ID}/topics/{t}"

sub_path = full_subscription_path(DLQ_SUB)
topic_path = full_topic_path(TARGET_TOPIC)

subscriber = pubsub_v1.SubscriberClient()
publisher = pubsub_v1.PublisherClient()

db = None
if not DRY_RUN:
    if not FIRESTORE_PROJECT_ID:
        raise RuntimeError("missing FIRESTORE_PROJECT_ID/GOOGLE_CLOUD_PROJECT for watermark writes")
    from google.cloud import firestore

    db = firestore.Client(project=FIRESTORE_PROJECT_ID, database=FIRESTORE_DATABASE)

def touch_run() -> None:
    if DRY_RUN:
        return
    assert db is not None
    ref = db.collection("ops_replay_runs").document(RUN_ID)
    now = utc_now()
    ref.set(
        {
            "runId": RUN_ID,
            "tool": "scripts/dlq_replay.sh",
            "createdAt": now,
            "lastUpdatedAt": now,
            "dlqSubscription": sub_path,
            "targetTopic": topic_path,
            f"topics.{topic_path}": True,
        },
        merge=True,
    )

def stable_event_doc_id(*, subscription: str, dlq_message_id: str) -> str:
    raw = f"{subscription}__{dlq_message_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def event_start_or_get_status(*, doc_id: str, dlq_message_id: str, dlq_publish_time: str, delivery_attempt: Optional[int], data: bytes, attrs: Dict[str, str]) -> str:
    if DRY_RUN:
        return "created"
    assert db is not None
    now = utc_now()
    ref = db.collection(col("ops_replay_events")).document(doc_id)
    doc = {
        "status": "started",
        "createdAt": now,
        "updatedAt": now,
        "firstRunId": RUN_ID,
        "lastRunId": RUN_ID,
        "runs": {RUN_ID: True},
        "dlqSubscription": sub_path,
        "dlqMessageId": dlq_message_id,
        "dlqPublishTime": dlq_publish_time,
        "deliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
        "targetTopic": topic_path,
        "dataBytes": int(len(data)),
        "dataSha256": sha256_hex(data),
        "attributesSha256": sha256_hex(repr(sorted(list(attrs.items()))).encode("utf-8")),
        "attributeKeys": sorted(list(attrs.keys()))[:200],
    }
    # Remove nulls.
    doc = {k: v for k, v in doc.items() if v is not None}
    try:
        ref.create(doc)
        return "created"
    except AlreadyExists:
        snap = ref.get()
        existing = snap.to_dict() if snap.exists else {}
        status = str((existing or {}).get("status") or "unknown")
        # Mark that this message was observed under this run.
        ref.set({"updatedAt": now, "lastRunId": RUN_ID, "runs": {RUN_ID: True}}, merge=True)
        return f"exists:{status}"

def event_update(*, doc_id: str, update: Dict[str, Any]) -> None:
    if DRY_RUN:
        return
    assert db is not None
    update = dict(update)
    update["updatedAt"] = utc_now()
    update["lastRunId"] = RUN_ID
    update["runs"] = {RUN_ID: True}
    db.collection(col("ops_replay_events")).document(doc_id).set(update, merge=True)

def run_touch() -> None:
    if DRY_RUN:
        return
    assert db is not None
    db.collection("ops_replay_runs").document(RUN_ID).set({"lastUpdatedAt": utc_now()}, merge=True)

def sleep_qps() -> None:
    if QPS <= 0:
        return
    time.sleep(1.0 / QPS)

touch_run()

processed = 0
while True:
    if MAX_MESSAGES and processed >= MAX_MESSAGES:
        print(f"Reached --max-messages={MAX_MESSAGES}; stopping.")
        break

    resp = subscriber.pull(subscription=sub_path, max_messages=BATCH_SIZE)
    received = list(resp.received_messages or [])
    if not received:
        print("DLQ empty (no messages returned).")
        break

    for rm in received:
        if MAX_MESSAGES and processed >= MAX_MESSAGES:
            break

        m = rm.message
        dlq_mid = (m.message_id or "").strip()
        if not dlq_mid:
            print("WARN: skipping message with missing message_id")
            continue

        pub_dt = m.publish_time.ToDatetime().replace(tzinfo=timezone.utc) if m.publish_time else utc_now()
        dlq_publish_time = pub_dt.isoformat()
        data = m.data or b""
        attrs = {str(k): ("" if v is None else str(v)) for k, v in dict(m.attributes or {}).items()}
        delivery_attempt = getattr(rm, "delivery_attempt", None)

        doc_id = stable_event_doc_id(subscription=sub_path, dlq_message_id=dlq_mid)
        status_line = event_start_or_get_status(
            doc_id=doc_id,
            dlq_message_id=dlq_mid,
            dlq_publish_time=dlq_publish_time,
            delivery_attempt=delivery_attempt,
            data=data,
            attrs=attrs,
        )

        if status_line.startswith("exists:"):
            prior = status_line.split(":", 1)[1]
            if prior in {"published", "acked"}:
                print(f"Replay skip (already {prior}): dlqMessageId={dlq_mid} doc={doc_id}")
                if not DRY_RUN:
                    subscriber.acknowledge(subscription=sub_path, ack_ids=[rm.ack_id])
                    event_update(doc_id=doc_id, update={"status": "acked", "ackedAt": utc_now()})
                    run_touch()
                processed += 1
                sleep_qps()
                continue

        if DRY_RUN:
            print(f"DRY RUN: would publish+ack dlqMessageId={dlq_mid} doc={doc_id} bytes={len(data)}")
            processed += 1
            sleep_qps()
            continue

        # Publish original bytes back to the target topic; add audit attributes (consumers tolerate unknown attrs).
        pub_attrs = dict(attrs)
        pub_attrs["replay_run_id"] = RUN_ID
        pub_attrs["replay_source_subscription"] = sub_path
        pub_attrs["replay_source_message_id"] = dlq_mid

        fut = publisher.publish(topic_path, data=data, **pub_attrs)
        republished_mid = fut.result(timeout=60)
        event_update(
            doc_id=doc_id,
            update={
                "status": "published",
                "republishedAt": utc_now(),
                "republishedTopic": topic_path,
                "republishedMessageId": str(republished_mid),
            },
        )

        # ACK only after publish+watermark update.
        subscriber.acknowledge(subscription=sub_path, ack_ids=[rm.ack_id])
        event_update(doc_id=doc_id, update={"status": "acked", "ackedAt": utc_now()})
        run_touch()

        processed += 1
        sleep_qps()

print(f"OK: replay complete. processed={processed} runId={RUN_ID}")
PY

