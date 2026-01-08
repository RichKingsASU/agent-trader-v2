from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
import traceback
from typing import Any, Optional, Tuple

from idempotency import ensure_message_once
from replay_support import ReplayContext, ensure_event_not_applied


def _as_utc(dt: datetime) -> datetime:
    return ensure_utc(dt, source="cloudrun_consumer.firestore_writer._as_utc", field="dt")


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="cloudrun_consumer.firestore_writer._parse_rfc3339", field="datetime")
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return ensure_utc(dt, source="cloudrun_consumer.firestore_writer._parse_rfc3339", field="iso_string")
    except Exception:
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "event_type": "firestore_writer.parse_rfc3339_failed",
                        "value": s[:256],
                        "exception": traceback.format_exc()[-8000:],
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
        return None


def _max_dt(*values: Optional[datetime]) -> Optional[datetime]:
    xs = [v for v in values if isinstance(v, datetime)]
    if not xs:
        return None
    return max(_as_utc(v) for v in xs)


@dataclass(frozen=True)
class SourceInfo:
    topic: str
    message_id: str
    published_at: datetime


class FirestoreWriter:
    def __init__(self, *, project_id: str, database: str = "(default)", collection_prefix: str = "") -> None:
        from google.cloud import firestore as firestore_mod

        self._firestore = firestore_mod
        self._db = firestore_mod.Client(project=project_id, database=database)
        self._collection_prefix = str(collection_prefix or "").strip()

    def _col(self, name: str) -> str:
        p = self._collection_prefix
        if not p:
            return str(name)
        # Keep simple; prefix should be Firestore-safe (no '/').
        return f"{p}{name}"

    @staticmethod
    def _stable_sample(message_id: str, *, rate: float) -> bool:
        """
        Deterministic sampling based on message_id (stable across retries).
        """
        try:
            r = float(rate)
        except Exception:
            r = 0.0
        if r <= 0.0:
            return False
        if r >= 1.0:
            return True
        mid = (message_id or "").strip()
        if not mid:
            return False
        h = hashlib.sha1(mid.encode("utf-8", errors="ignore")).digest()
        x = int.from_bytes(h[:4], "big") / float(2**32)
        return x < r

    @staticmethod
    def _truncate_str(value: Any, *, max_len: int) -> str:
        s = "" if value is None else str(value)
        if max_len <= 0:
            return ""
        return s if len(s) <= max_len else (s[: max_len - 1] + "…")

    @staticmethod
    def _sanitize_payload(value: Any) -> Any:
        """
        Best-effort scrub for secrets/PII in sampled DLQ docs.
        """
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
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                ks = str(k).lower()
                if ks in SENSITIVE_KEYS:
                    out[str(k)] = "[redacted]"
                else:
                    out[str(k)] = FirestoreWriter._sanitize_payload(v)
            return out
        if isinstance(value, list):
            return [FirestoreWriter._sanitize_payload(v) for v in value[:50]]
        return value

    def maybe_write_sampled_dlq_event(
        self,
        *,
        message_id: str,
        subscription: str,
        topic: str,
        handler: str,
        http_status: int,
        reason: str,
        error: str,
        delivery_attempt: Optional[int],
        attributes: dict[str, str],
        payload: Optional[dict[str, Any]],
        sample_rate: float,
        ttl_hours: float,
    ) -> bool:
        """
        Best-effort: writes a sampled DLQ-candidate doc into Firestore.

        Retention is bounded via `expiresAt` (TTL field; enable TTL on collection group `sampled_dlq`).
        Sampling is deterministic on `message_id` to avoid repeated writes on retries.
        """
        if not self._stable_sample(message_id, rate=sample_rate):
            return False

        now = datetime.now(timezone.utc)
        try:
            hours = float(ttl_hours)
        except Exception:
            hours = 72.0
        if hours <= 0:
            return False

        doc_id = (message_id or "").strip() or hashlib.sha1(str(now).encode("utf-8")).hexdigest()[:32]
        doc_ref = self._db.collection("sampled_dlq").document(doc_id)

        safe_payload = self._sanitize_payload(payload) if isinstance(payload, dict) else None
        payload_json = ""
        try:
            payload_json = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            payload_json = ""
        max_payload_chars = 24_000  # Firestore doc limit guardrail (best-effort)
        payload_too_large = bool(payload_json) and (len(payload_json) > max_payload_chars)

        doc: dict[str, Any] = {
            "messageId": (message_id or "").strip(),
            "subscription": (subscription or "").strip(),
            "topic": (topic or "").strip(),
            "handler": (handler or "").strip(),
            "httpStatus": int(http_status),
            "reason": self._truncate_str(reason, max_len=256),
            "error": self._truncate_str(error, max_len=2048),
            "deliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
            "attributes": dict(attributes or {}),
            "receivedAt": now,
            "expiresAt": now + timedelta(hours=hours),
        }

        if safe_payload is not None and not payload_too_large:
            doc["payload"] = safe_payload
            doc["payloadTruncated"] = False
        elif payload_json:
            doc["payloadJsonSnippet"] = self._truncate_str(payload_json, max_len=max_payload_chars)
            doc["payloadTruncated"] = True

        # Remove nulls for cleaner docs.
        doc = {k: v for k, v in doc.items() if v is not None}
        try:
            doc_ref.set(doc, merge=False)
            return True
        except Exception:
            # Never fail the request path due to DLQ sampling.
            return False

    def _upsert_event_doc(
        self,
        *,
        collection: str,
        doc_id: str,
        event_time: datetime,
        source: SourceInfo,
        doc: dict[str, Any],
        replay: Optional[ReplayContext] = None,
        replay_dedupe_key: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Generic upsert with stale protection:
        - doc id is deterministic (eventId if present else messageId)
        - ignore stale updates based on event_time vs existing produced/published/eventTime/source.publishedAt
        """
        ref = self._db.collection(self._col(collection)).document(doc_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            if replay is not None:
                ok, why = ensure_event_not_applied(
                    txn=txn,
                    db=self._db,
                    replay=replay,
                    dedupe_key=str(replay_dedupe_key or doc_id),
                    event_time=_as_utc(event_time),
                    message_id=str(source.message_id),
                )
                if not ok:
                    return False, why

            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_event_time = None
            if isinstance(existing, dict):
                existing_event_time = _parse_rfc3339(existing.get("eventTime"))
                existing_produced_at = _parse_rfc3339(existing.get("producedAt"))
                existing_published_at = _parse_rfc3339(existing.get("publishedAt"))
                existing_source_pub = None
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))
                existing_max = _max_dt(existing_event_time, existing_produced_at, existing_published_at, existing_source_pub)
            else:
                existing_max = None

            incoming = _as_utc(event_time)
            if existing_max is not None and incoming < existing_max:
                return False, "stale_event_ignored"

            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def upsert_market_tick(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_market_tick", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_market_tick", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        # Remove nulls for cleaner docs.
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_ticks",
            doc_id=doc_id,
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_market_bar_1m(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        timeframe: Optional[str],
        start: Optional[datetime],
        end: Optional[datetime],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "start": ensure_utc(start, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="start") if isinstance(start, datetime) else start,
            "end": ensure_utc(end, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="end") if isinstance(end, datetime) else end,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_bars_1m",
            doc_id=doc_id,
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_trade_signal(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        strategy: Optional[str],
        action: Optional[str],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "strategy": strategy,
            "action": action,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_trade_signal", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_trade_signal", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="trade_signals",
            doc_id=doc_id,
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_ops_service(
        self,
        *,
        service_id: str,
        env: str,
        status: str,
        last_heartbeat_at: Optional[datetime],
        version: str,
        region: str,
        updated_at: datetime,
        source: SourceInfo,
    ) -> Tuple[bool, str]:
        """
        Writes `ops_services/{serviceId}` with stale protection.

        Stale protection rule (per mission):
        - only overwrite if incoming `updated_at` >= max(stored.lastHeartbeatAt, stored.updatedAt)
        """
        ref = self._db.collection(self._col("ops_services")).document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_u)

            incoming = _as_utc(updated_at)
            if existing_max is not None and incoming < existing_max:
                return False, "stale_event_ignored"

            doc = {
                "serviceId": str(service_id),
                "env": str(env),
                "status": str(status),
                "lastHeartbeatAt": ensure_utc(last_heartbeat_at, source="cloudrun_consumer.firestore_writer.upsert_ops_service", field="last_heartbeat_at") if isinstance(last_heartbeat_at, datetime) else last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                "updatedAt": incoming,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def dedupe_and_upsert_ops_service(
        self,
        *,
        message_id: str,
        replay: Optional[ReplayContext] = None,
        replay_dedupe_key: Optional[str] = None,
        service_id: str,
        env: str,
        status: str,
        last_heartbeat_at: Optional[datetime],
        version: str,
        region: str,
        updated_at: datetime,
        source: SourceInfo,
    ) -> Tuple[bool, str]:
        """
        Transactionally:
        - checks/creates `ops_dedupe/{messageId}`
        - applies stale-protected write to ops_services
        """
        dedupe_ref = self._db.collection(self._col("ops_dedupe")).document(message_id)
        service_ref = self._db.collection(self._col("ops_services")).document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            first_time, _ = ensure_message_once(txn=txn, dedupe_ref=dedupe_ref, message_id=message_id)
            if not first_time:
                return False, "duplicate_message_noop"

            if replay is not None:
                ok, why = ensure_event_not_applied(
                    txn=txn,
                    db=self._db,
                    replay=replay,
                    dedupe_key=str(replay_dedupe_key or message_id),
                    event_time=_as_utc(updated_at),
                    message_id=str(message_id),
                )
                if not ok:
                    return False, why

            snap = service_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_u)

            incoming = _as_utc(updated_at)
            if existing_max is not None and incoming < existing_max:
                # Marked dedupe already; do not reprocess on retries.
                return False, "stale_event_ignored"

            doc = {
                "serviceId": str(service_id),
                "env": str(env),
                "status": str(status),
                "lastHeartbeatAt": ensure_utc(last_heartbeat_at, source="cloudrun_consumer.firestore_writer.dedupe_and_upsert_ops_service", field="last_heartbeat_at") if isinstance(last_heartbeat_at, datetime) else last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                "updatedAt": incoming,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(service_ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

