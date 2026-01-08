"""
vm_ingest (Cloud Run / Docker only)

This module is intentionally container-first:
- No host/VM execution paths
- No sys.path hacks
- Uses Application Default Credentials (Cloud Run service account) or an explicitly
  provided service account JSON in Docker.
"""

from __future__ import annotations

import base64
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# Per task requirement: keep these imports exactly (no lazy import indirection).
from google.cloud import pubsub_v1, secretmanager
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


@dataclass(frozen=True)
class Config:
    pubsub_project_id: str
    subscription_id: str
    firestore_project_id: Optional[str]
    firestore_collection: str
    config_secret_version: Optional[str]
    max_messages: int


def _load_config_from_env() -> Config:
    pubsub_project_id = (
        _env("PUBSUB_PROJECT_ID")
        or _env("GOOGLE_CLOUD_PROJECT")
        or _env("GCP_PROJECT")
        or ""
    )
    subscription_id = _env("PUBSUB_SUBSCRIPTION_ID") or ""

    firestore_project_id = _env("FIRESTORE_PROJECT_ID") or _env("GOOGLE_CLOUD_PROJECT") or None
    firestore_collection = _env("FIRESTORE_COLLECTION", "vm_ingest_events") or "vm_ingest_events"

    config_secret_version = _env("VM_INGEST_CONFIG_SECRET_VERSION")

    try:
        max_messages = int(_env("VM_INGEST_MAX_IN_FLIGHT", "50") or "50")
    except Exception:
        max_messages = 50
    max_messages = max(1, min(1000, max_messages))

    return Config(
        pubsub_project_id=str(pubsub_project_id),
        subscription_id=str(subscription_id),
        firestore_project_id=str(firestore_project_id) if firestore_project_id is not None else None,
        firestore_collection=str(firestore_collection),
        config_secret_version=str(config_secret_version) if config_secret_version else None,
        max_messages=int(max_messages),
    )


def _maybe_apply_secret_config(cfg: Config) -> Config:
    """
    Optionally load JSON config from Secret Manager.

    Env:
      VM_INGEST_CONFIG_SECRET_VERSION=projects/.../secrets/.../versions/latest

    JSON keys (all optional):
      pubsub_project_id, subscription_id, firestore_project_id, firestore_collection, max_messages
    """
    if not cfg.config_secret_version:
        return cfg

    sm = secretmanager.SecretManagerServiceClient()
    resp = sm.access_secret_version(request={"name": cfg.config_secret_version})
    raw = (resp.payload.data or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        return cfg

    try:
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError("Secret config is not valid JSON.") from e
    if not isinstance(data, dict):
        raise RuntimeError("Secret config must be a JSON object.")

    pubsub_project_id = str(data.get("pubsub_project_id") or cfg.pubsub_project_id).strip()
    subscription_id = str(data.get("subscription_id") or cfg.subscription_id).strip()

    firestore_project_id = data.get("firestore_project_id")
    if firestore_project_id is None:
        firestore_project_id_s = cfg.firestore_project_id
    else:
        firestore_project_id_s = str(firestore_project_id).strip() or None

    firestore_collection = str(data.get("firestore_collection") or cfg.firestore_collection).strip() or cfg.firestore_collection

    max_messages_v = data.get("max_messages")
    if max_messages_v is None:
        max_messages = cfg.max_messages
    else:
        try:
            max_messages = int(max_messages_v)
        except Exception:
            max_messages = cfg.max_messages
    max_messages = max(1, min(1000, max_messages))

    return Config(
        pubsub_project_id=pubsub_project_id,
        subscription_id=subscription_id,
        firestore_project_id=firestore_project_id_s,
        firestore_collection=firestore_collection,
        config_secret_version=cfg.config_secret_version,
        max_messages=max_messages,
    )


def _firestore_client(project_id: Optional[str]) -> firestore.Client:
    if project_id:
        return firestore.Client(project=project_id)
    return firestore.Client()


def _doc_for_message(message: Any) -> dict[str, Any]:
    """
    Build a Firestore-safe document for a Pub/Sub message.

    This is at-least-once safe by using message_id as doc id.
    """
    data_bytes: bytes = getattr(message, "data", b"") or b""
    original_len = len(data_bytes)
    attrs: dict[str, str] = dict(getattr(message, "attributes", {}) or {})
    message_id = str(getattr(message, "message_id", "") or "")
    publish_time = getattr(message, "publish_time", None)
    publish_time_s: Optional[str]
    try:
        publish_time_s = publish_time.isoformat() if publish_time is not None else None
    except Exception:
        publish_time_s = None

    # Prefer utf-8 text; fall back to base64.
    text: Optional[str]
    try:
        text = data_bytes.decode("utf-8")
    except Exception:
        text = None

    # Firestore doc size limit is ~1MiB; keep payload bounded and explicit.
    # If text is too large, we store only a base64 prefix + size metadata.
    max_bytes = 900_000
    truncated = False
    if len(data_bytes) > max_bytes:
        truncated = True
        data_bytes = data_bytes[:max_bytes]
        if text is not None:
            text = text[: max_bytes // 4]  # conservative bound for utf-8 vs chars

    raw_b64 = base64.b64encode(data_bytes).decode("ascii")

    return {
        "ingestedAt": _utcnow_iso(),
        "messageId": message_id,
        "publishTime": publish_time_s,
        "attributes": attrs,
        "dataUtf8": text,
        "dataBase64": raw_b64,
        "dataOriginalBytes": int(original_len),
        "dataTruncated": bool(truncated),
    }


def run() -> int:
    cfg = _maybe_apply_secret_config(_load_config_from_env())
    if not cfg.pubsub_project_id:
        raise RuntimeError("Missing PUBSUB_PROJECT_ID (or GOOGLE_CLOUD_PROJECT).")
    if not cfg.subscription_id:
        raise RuntimeError("Missing PUBSUB_SUBSCRIPTION_ID.")

    db = _firestore_client(cfg.firestore_project_id)
    sub = pubsub_v1.SubscriberClient()
    subscription_path = sub.subscription_path(cfg.pubsub_project_id, cfg.subscription_id)

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: Any | None = None) -> None:
        stop.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, _handle_signal)

    print(
        json.dumps(
            {
                "event_type": "startup",
                "ts": _utcnow_iso(),
                "service": "vm-ingest",
                "subscription": subscription_path,
                "firestore_project_id": cfg.firestore_project_id,
                "firestore_collection": cfg.firestore_collection,
                "max_in_flight": cfg.max_messages,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )

    collection = db.collection(cfg.firestore_collection)

    def _callback(message: Any) -> None:
        message_id = str(getattr(message, "message_id", "") or "")
        if not message_id:
            # Pub/Sub messages should always have an id. If not, force retry/DLQ.
            message.nack()
            return
        doc_ref = collection.document(message_id)
        try:
            doc = _doc_for_message(message)
            # Idempotent: create() succeeds once; duplicates are treated as already processed.
            doc_ref.create(doc)
            message.ack()
        except AlreadyExists:
            message.ack()
        except Exception as e:
            # Retry on transient failures by nacking.
            try:
                print(
                    json.dumps(
                        {
                            "event_type": "message_error",
                            "ts": _utcnow_iso(),
                            "service": "vm-ingest",
                            "messageId": message_id,
                            "errorType": e.__class__.__name__,
                            "error": str(e),
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception:
                pass
            message.nack()

    flow = pubsub_v1.types.FlowControl(max_messages=cfg.max_messages)
    future = sub.subscribe(subscription_path, callback=_callback, flow_control=flow)

    try:
        while not stop.is_set():
            time.sleep(0.25)
        future.cancel()
        try:
            future.result(timeout=10)
        except Exception:
            pass
    finally:
        try:
            sub.close()
        except Exception:
            pass

    print(
        json.dumps(
            {"event_type": "shutdown", "ts": _utcnow_iso(), "service": "vm-ingest", "status": "ok"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

