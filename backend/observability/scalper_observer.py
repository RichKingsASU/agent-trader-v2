"""
READ-ONLY SCALPER OBSERVER LIBRARY

Read-only guarantees (MANDATORY):
- No broker imports
- No execution_service imports
- No writes to Firestore (no set/create/update/delete/add/batch.commit)
- No writes to any DB
- No network calls except Firestore READS (and only via existing repo Firestore client)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, MutableMapping, Optional, Sequence, TypedDict, cast

from backend.persistence.firebase_client import get_firestore_client
from backend.time.nyse_time import parse_ts


class ReasonCode(str, Enum):
    """
    Stable reason codes for explanation diagnostics.

    These are intended for machines (UI, tests, operators). Do not change existing values.
    """

    # Input / query
    MISSING_QUERY = "missing_query"
    INVALID_TIME_RANGE = "invalid_time_range"

    # Firestore access / reads
    FIRESTORE_CLIENT_UNAVAILABLE = "firestore_client_unavailable"
    FIRESTORE_READ_FAILED = "firestore_read_failed"

    # Correlation outcomes
    NO_MATCHING_SIGNAL = "no_matching_signal"
    MULTIPLE_SIGNALS_MATCHED = "multiple_signals_matched"
    NO_MATCHING_SHADOW_TRADE = "no_matching_shadow_trade"
    MARKET_REGIME_UNAVAILABLE = "market_regime_unavailable"

    # Structured events
    EVENTS_NOT_PROVIDED = "events_not_provided"
    EVENTS_FILTERED_EMPTY = "events_filtered_empty"


class EvidenceDoc(TypedDict, total=False):
    """
    Generic evidence wrapper around a Firestore document or structured event.
    """

    # A stable pointer for operators. Format examples:
    # - firestore:tradingSignals/<id>
    # - firestore:trade_signals/<id>
    # - firestore:users/<uid>/shadowTradeHistory/<id>
    ref: str
    # Best-effort timestamp for sorting (ISO-8601 string).
    ts: str
    # Raw content (Firestore dict or event dict).
    data: dict[str, Any]


class NormalizedEvent(TypedDict, total=False):
    """
    Normalized structured event (best-effort).
    """

    ts: str
    event_type: str
    severity: str
    correlation_id: str
    signal_id: str
    client_intent_id: str
    execution_id: str
    message: str
    fields: dict[str, Any]


class ExplanationRecord(TypedDict, total=False):
    """
    Explanation record (observer output).

    Notes:
    - This shape is designed to be JSON-serializable.
    - Fields are best-effort; missing inputs/data yield partial explanations plus reason codes.
    """

    protocol: str
    generated_at: str

    # Query inputs as received.
    query: dict[str, Any]

    # Resolved identifiers (best-effort).
    signal_id: Optional[str]
    correlation_id: Optional[str]
    client_intent_id: Optional[str]

    # High-level decision summary (best-effort).
    decision: dict[str, Any]

    # Diagnostics
    ok: bool
    reason_codes: list[str]
    warnings: list[str]

    # Evidence and timeline
    evidence: dict[str, Any]
    timeline: list[NormalizedEvent]


@dataclass(frozen=True)
class _TimeWindow:
    tmin: Optional[datetime]
    tmax: Optional[datetime]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_id(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _as_iso(ts: Any) -> Optional[str]:
    """
    Convert Firestore timestamps / datetime / ISO strings to ISO-8601 UTC strings.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        try:
            dt = parse_ts(s)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return s
    # Firestore Timestamp-like objects often provide .datetime or are datetime-compatible; best-effort.
    dt_attr = getattr(ts, "datetime", None)
    if isinstance(dt_attr, datetime):
        dt = dt_attr
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    try:
        return str(ts)
    except Exception:
        return None


def _parse_window(*, time_min: str | None, time_max: str | None) -> tuple[_TimeWindow, list[str], list[str]]:
    reasons: list[str] = []
    warnings: list[str] = []
    tmin = None
    tmax = None
    if _clean_id(time_min):
        try:
            tmin = parse_ts(str(time_min))
        except Exception:
            warnings.append(f"failed_to_parse_time_min:{time_min}")
    if _clean_id(time_max):
        try:
            tmax = parse_ts(str(time_max))
        except Exception:
            warnings.append(f"failed_to_parse_time_max:{time_max}")
    if tmin and tmax and tmin > tmax:
        reasons.append(ReasonCode.INVALID_TIME_RANGE.value)
        # Swap to keep queries usable.
        tmin, tmax = tmax, tmin
    return _TimeWindow(tmin=tmin, tmax=tmax), reasons, warnings


def _safe_to_dict(snap: Any) -> dict[str, Any]:
    try:
        if snap is None:
            return {}
        to_dict = getattr(snap, "to_dict", None)
        if callable(to_dict):
            out = to_dict() or {}
            return dict(out) if isinstance(out, Mapping) else {}
        if isinstance(snap, Mapping):
            return dict(snap)
    except Exception:
        return {}
    return {}


def _event_match_ids(
    ev: Mapping[str, Any],
    *,
    signal_id: str | None,
    correlation_id: str | None,
    client_intent_id: str | None,
) -> bool:
    """
    Best-effort filter for structured events based on common key variants.
    """
    sid = _clean_id(signal_id)
    cid = _clean_id(correlation_id)
    iid = _clean_id(client_intent_id)

    def _get(*keys: str) -> str | None:
        for k in keys:
            v = ev.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return None

    ev_sid = _get("signal_id", "signalId")
    ev_cid = _get("correlation_id", "correlationId", "request_id", "requestId", "trace_id", "traceId")
    ev_iid = _get("client_intent_id", "clientIntentId", "intent_id", "intentId")

    if sid and ev_sid == sid:
        return True
    if cid and ev_cid == cid:
        return True
    if iid and ev_iid == iid:
        return True
    return False


def _normalize_event(ev: Mapping[str, Any]) -> NormalizedEvent:
    def _get(*keys: str) -> str | None:
        for k in keys:
            v = ev.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return None

    ts = _as_iso(_get("ts", "timestamp", "time", "eventTime")) or _utc_now_iso()
    event_type = _get("event_type", "eventType", "type", "event") or "event"
    severity = (_get("severity", "level") or "INFO").upper()
    message = _get("message", "msg") or None

    return NormalizedEvent(
        ts=ts,
        event_type=event_type,
        severity=severity,
        correlation_id=_get("correlation_id", "correlationId", "request_id", "requestId") or "",
        signal_id=_get("signal_id", "signalId") or "",
        client_intent_id=_get("client_intent_id", "clientIntentId", "intent_id", "intentId") or "",
        execution_id=_get("execution_id", "executionId") or "",
        message=message or "",
        fields=dict(ev),
    )


def _within_window(dt: datetime, w: _TimeWindow) -> bool:
    if w.tmin and dt < w.tmin:
        return False
    if w.tmax and dt > w.tmax:
        return False
    return True


def _best_effort_dt_from_doc(doc: Mapping[str, Any], *keys: str) -> Optional[datetime]:
    for k in keys:
        if k not in doc:
            continue
        v = doc.get(k)
        if isinstance(v, datetime):
            return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            try:
                return parse_ts(s)
            except Exception:
                continue
        dt_attr = getattr(v, "datetime", None)
        if isinstance(dt_attr, datetime):
            return dt_attr if dt_attr.tzinfo is not None else dt_attr.replace(tzinfo=timezone.utc)
    return None


def _extract_decision_from_any(*, trading_signal: dict[str, Any] | None, trade_signal: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize a minimal "decision" summary.
    """
    out: dict[str, Any] = {}

    # Prefer trade_signals (canonical ingest read-model), then tradingSignals (legacy dashboard).
    src = trade_signal if isinstance(trade_signal, dict) and trade_signal else trading_signal
    if not isinstance(src, dict):
        return out

    # `trade_signals` stores payload under `data`; `tradingSignals` stores fields at top-level.
    payload: dict[str, Any]
    if "data" in src and isinstance(src.get("data"), dict):
        payload = cast(dict[str, Any], src.get("data") or {})
    else:
        payload = dict(src)

    out["symbol"] = payload.get("symbol") or src.get("symbol")
    out["strategy"] = payload.get("strategy") or payload.get("strategyId") or src.get("strategy") or src.get("strategy_name")
    out["action"] = payload.get("action") or payload.get("side") or src.get("action")
    out["state"] = payload.get("state") or payload.get("status") or src.get("state")
    out["confidence"] = payload.get("confidence") or src.get("confidence")
    out["reason"] = payload.get("reason") or payload.get("rationale") or src.get("reason")

    decided_at = _best_effort_dt_from_doc(payload, "updatedAt", "decisionAt", "createdAt", "timestamp", "ts")
    if decided_at is None:
        decided_at = _best_effort_dt_from_doc(src, "eventTime", "producedAt", "publishedAt", "timestamp", "created_at", "created_at_iso")
    if decided_at is not None:
        out["decided_at"] = decided_at.astimezone(timezone.utc).isoformat()
    return {k: v for k, v in out.items() if v is not None}


def _ensure_firestore_db() -> tuple[Any | None, list[str], list[str]]:
    reasons: list[str] = []
    warnings: list[str] = []
    try:
        db = get_firestore_client()
        return db, reasons, warnings
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_CLIENT_UNAVAILABLE.value)
        warnings.append(f"firestore_client_error:{type(e).__name__}:{e}")
        return None, reasons, warnings


def _read_doc(db: Any, *, collection: str, doc_id: str) -> tuple[dict[str, Any] | None, EvidenceDoc | None, list[str]]:
    reasons: list[str] = []
    did = _clean_id(doc_id)
    if not did:
        return None, None, reasons
    try:
        snap = db.collection(str(collection)).document(str(did)).get()
        if not getattr(snap, "exists", False):
            return None, None, reasons
        data = _safe_to_dict(snap)
        ts = _as_iso(_best_effort_dt_from_doc(data, "timestamp", "eventTime", "created_at", "created_at_iso", "updatedAt", "decisionAt"))
        ev = EvidenceDoc(ref=f"firestore:{collection}/{did}", ts=ts or "", data=data)
        return data, ev, reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_READ_FAILED.value)
        reasons.append(f"read_failed:{collection}:{type(e).__name__}")
        return None, None, reasons


def _query_collection_best_effort(
    db: Any,
    *,
    collection: str,
    time_field: str,
    w: _TimeWindow,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Best-effort time-window scan for a collection.

    This avoids inventing any log datastore. It is intentionally conservative:
    - only uses simple where/order_by patterns
    - falls back to latest N docs when range queries fail
    """
    reasons: list[str] = []
    docs: list[dict[str, Any]] = []
    try:
        q = db.collection(str(collection))
        # Prefer bounded range query when we have at least one bound.
        if w.tmin is not None:
            q = q.where(str(time_field), ">=", w.tmin)
        if w.tmax is not None:
            q = q.where(str(time_field), "<=", w.tmax)
        try:
            q = q.order_by(str(time_field), direction="DESCENDING")
        except Exception:
            # Some Firestore clients require an index for order_by+where; skip ordering if it fails.
            pass
        q = q.limit(int(max(1, min(500, limit))))
        for snap in q.stream():
            d = _safe_to_dict(snap)
            if d:
                docs.append(d)
        return docs, reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_READ_FAILED.value)
        reasons.append(f"query_failed:{collection}:{type(e).__name__}")

    # Fallback: grab latest N without range filtering; filter in-memory.
    try:
        q2 = db.collection(str(collection))
        try:
            q2 = q2.order_by(str(time_field), direction="DESCENDING")
        except Exception:
            pass
        q2 = q2.limit(int(max(1, min(500, limit))))
        for snap in q2.stream():
            d = _safe_to_dict(snap)
            if not d:
                continue
            dt = _best_effort_dt_from_doc(d, time_field, "timestamp", "eventTime", "created_at", "created_at_iso", "updatedAt", "decisionAt")
            if dt is not None and _within_window(dt, w):
                docs.append(d)
        return docs, reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_READ_FAILED.value)
        reasons.append(f"fallback_query_failed:{collection}:{type(e).__name__}")
        return docs, reasons


def _find_matching_doc_by_ids(
    docs: Sequence[Mapping[str, Any]],
    *,
    signal_id: str | None,
    correlation_id: str | None,
    client_intent_id: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Find a best matching document in a list by common identifier keys.
    """
    reasons: list[str] = []
    sid = _clean_id(signal_id)
    cid = _clean_id(correlation_id)
    iid = _clean_id(client_intent_id)
    if not docs:
        return None, reasons

    def _match(d: Mapping[str, Any]) -> bool:
        # Common top-level keys.
        for k in ("signal_id", "signalId", "signal_id", "docId"):
            if sid and str(d.get(k) or "").strip() == sid:
                return True
        for k in ("correlation_id", "correlationId"):
            if cid and str(d.get(k) or "").strip() == cid:
                return True
        for k in ("client_intent_id", "clientIntentId", "intent_id", "intentId"):
            if iid and str(d.get(k) or "").strip() == iid:
                return True

        # Nested payload (trade_signals stores under data).
        p = d.get("data") if isinstance(d.get("data"), dict) else None
        if isinstance(p, dict):
            if sid and str(p.get("signal_id") or p.get("signalId") or "").strip() == sid:
                return True
            if cid and str(p.get("correlation_id") or p.get("correlationId") or "").strip() == cid:
                return True
            if iid and str(p.get("client_intent_id") or p.get("clientIntentId") or "").strip() == iid:
                return True
        return False

    matches = [dict(d) for d in docs if _match(d)]
    if not matches:
        return None, reasons
    if len(matches) > 1:
        reasons.append(ReasonCode.MULTIPLE_SIGNALS_MATCHED.value)
    return matches[0], reasons


def _best_effort_uid_from_docs(*, trading_signal: dict[str, Any] | None, trade_signal: dict[str, Any] | None) -> str | None:
    for src in (trade_signal, trading_signal):
        if not isinstance(src, dict):
            continue
        # trade_signals embeds payload under data
        payload = src.get("data") if isinstance(src.get("data"), dict) else src
        if isinstance(payload, dict):
            for k in ("uid", "user_id", "userId"):
                v = payload.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
    return None


def _read_shadow_trade_by_uid_and_corr(
    db: Any,
    *,
    uid: str,
    correlation_id: str | None,
    w: _TimeWindow,
) -> tuple[dict[str, Any] | None, EvidenceDoc | None, list[str]]:
    """
    Read a user-scoped shadow trade that best matches correlation/idempotency key.
    """
    reasons: list[str] = []
    uid = str(uid).strip()
    cid = _clean_id(correlation_id)
    if not uid or not cid:
        return None, None, reasons

    col = db.collection("users").document(uid).collection("shadowTradeHistory")

    # Prefer query by idempotency_key, because shadow trades store it.
    try:
        q = col.where("idempotency_key", "==", cid).limit(5)
        hits = list(q.stream())
        if hits:
            snap = hits[0]
            data = _safe_to_dict(snap)
            did = str(getattr(snap, "id", "") or data.get("shadow_id") or "")
            ts = _as_iso(_best_effort_dt_from_doc(data, "created_at", "created_at_iso", "last_updated"))
            return data, EvidenceDoc(ref=f"firestore:users/{uid}/shadowTradeHistory/{did}", ts=ts or "", data=data), reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_READ_FAILED.value)
        reasons.append(f"shadow_query_failed:{type(e).__name__}")

    # Fallback: scan recent trades in window and match in-memory on idempotency_key.
    try:
        q2 = col
        try:
            q2 = q2.order_by("created_at", direction="DESCENDING")
        except Exception:
            pass
        q2 = q2.limit(200)
        for snap in q2.stream():
            data = _safe_to_dict(snap)
            if not data:
                continue
            if str(data.get("idempotency_key") or "").strip() != cid:
                continue
            dt = _best_effort_dt_from_doc(data, "created_at", "created_at_iso", "last_updated")
            if dt is not None and not _within_window(dt, w):
                continue
            did = str(getattr(snap, "id", "") or data.get("shadow_id") or "")
            ts = _as_iso(dt) or ""
            return data, EvidenceDoc(ref=f"firestore:users/{uid}/shadowTradeHistory/{did}", ts=ts, data=data), reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.FIRESTORE_READ_FAILED.value)
        reasons.append(f"shadow_fallback_scan_failed:{type(e).__name__}")

    return None, None, reasons


def _read_market_regime(db: Any) -> tuple[dict[str, Any] | None, EvidenceDoc | None, list[str]]:
    reasons: list[str] = []
    try:
        snap = db.collection("systemStatus").document("market_regime").get()
        if not getattr(snap, "exists", False):
            return None, None, [ReasonCode.MARKET_REGIME_UNAVAILABLE.value]
        data = _safe_to_dict(snap)
        ts = _as_iso(_best_effort_dt_from_doc(data, "updated_at", "updatedAt", "timestamp"))
        return data, EvidenceDoc(ref="firestore:systemStatus/market_regime", ts=ts or "", data=data), reasons
    except Exception as e:  # noqa: BLE001
        reasons.append(ReasonCode.MARKET_REGIME_UNAVAILABLE.value)
        reasons.append(f"market_regime_read_failed:{type(e).__name__}")
        return None, None, reasons


def explain_scalper_decision(
    *,
    signal_id: str | None = None,
    correlation_id: str | None = None,
    client_intent_id: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    structured_events: Sequence[Mapping[str, Any]] | None = None,
) -> ExplanationRecord:
    """
    Explain a scalper decision by correlating read-only sources.

    Sources (best-effort):
    - Firestore `tradingSignals/{signal_id}` OR query by correlation_id/time window
    - Firestore `trade_signals/{docId}` OR time-window scan + id match
    - Firestore user-scoped `users/{uid}/shadowTradeHistory/*` (when uid can be inferred)
      - correlates via `idempotency_key == correlation_id` (shadow trades store this)
    - Firestore `systemStatus/market_regime` (optional context)
    - Structured events (optional parameter; no log datastore is assumed)
    """
    sid = _clean_id(signal_id)
    cid = _clean_id(correlation_id)
    iid = _clean_id(client_intent_id)

    window, window_reasons, window_warnings = _parse_window(time_min=time_min, time_max=time_max)
    reason_codes: list[str] = list(window_reasons)
    warnings: list[str] = list(window_warnings)

    if not (sid or cid or iid or window.tmin or window.tmax):
        reason_codes.append(ReasonCode.MISSING_QUERY.value)
        return ExplanationRecord(
            protocol="scalper_observer.v1",
            generated_at=_utc_now_iso(),
            query={
                "signal_id": sid,
                "correlation_id": cid,
                "client_intent_id": iid,
                "time_min": time_min,
                "time_max": time_max,
                "structured_events_provided": bool(structured_events),
            },
            signal_id=sid,
            correlation_id=cid,
            client_intent_id=iid,
            decision={},
            ok=False,
            reason_codes=sorted(set(reason_codes)),
            warnings=warnings,
            evidence={},
            timeline=[],
        )

    db, db_reasons, db_warnings = _ensure_firestore_db()
    reason_codes.extend(db_reasons)
    warnings.extend(db_warnings)

    # Evidence accumulator.
    evidence: dict[str, Any] = {
        "tradingSignals": None,
        "trade_signals": None,
        "shadowTradeHistory": None,
        "market_regime": None,
        "execution_reservation": None,
    }

    trading_signal_doc: dict[str, Any] | None = None
    trade_signal_doc: dict[str, Any] | None = None
    shadow_trade_doc: dict[str, Any] | None = None
    market_regime_doc: dict[str, Any] | None = None

    # (1) Firestore: tradingSignals (legacy dashboard signals)
    if db is not None:
        if sid:
            d, ev, rs = _read_doc(db, collection="tradingSignals", doc_id=sid)
            reason_codes.extend(rs)
            trading_signal_doc = d
            evidence["tradingSignals"] = ev
        if trading_signal_doc is None and cid:
            # Best-effort query: correlation_id exact match, plus optional time window.
            try:
                q = db.collection("tradingSignals").where("correlation_id", "==", cid)
                if window.tmin is not None:
                    q = q.where("timestamp", ">=", window.tmin)
                if window.tmax is not None:
                    q = q.where("timestamp", "<=", window.tmax)
                q = q.limit(10)
                hits = list(q.stream())
                if hits:
                    snap = hits[0]
                    trading_signal_doc = _safe_to_dict(snap)
                    did = str(getattr(snap, "id", "") or trading_signal_doc.get("signal_id") or "")
                    ts = _as_iso(_best_effort_dt_from_doc(trading_signal_doc, "timestamp", "created_at"))
                    evidence["tradingSignals"] = EvidenceDoc(
                        ref=f"firestore:tradingSignals/{did}",
                        ts=ts or "",
                        data=trading_signal_doc,
                    )
            except Exception as e:  # noqa: BLE001
                reason_codes.append(ReasonCode.FIRESTORE_READ_FAILED.value)
                warnings.append(f"tradingSignals_query_failed:{type(e).__name__}:{e}")

    # (2) Firestore: trade_signals (canonical ingest read-model)
    if db is not None:
        if sid:
            d, ev, rs = _read_doc(db, collection="trade_signals", doc_id=sid)
            reason_codes.extend(rs)
            trade_signal_doc = d
            evidence["trade_signals"] = ev
        # If doc id isn't signal_id, scan within time window when provided, or small recent scan.
        if trade_signal_doc is None:
            scan_w = window
            docs, rs = _query_collection_best_effort(db, collection="trade_signals", time_field="eventTime", w=scan_w, limit=200)
            reason_codes.extend(rs)
            matched, rs2 = _find_matching_doc_by_ids(docs, signal_id=sid, correlation_id=cid, client_intent_id=iid)
            reason_codes.extend(rs2)
            trade_signal_doc = matched
            if trade_signal_doc is not None:
                doc_id = str(trade_signal_doc.get("docId") or trade_signal_doc.get("signal_id") or trade_signal_doc.get("signalId") or "")
                ts = _as_iso(_best_effort_dt_from_doc(trade_signal_doc, "eventTime", "producedAt", "publishedAt"))
                evidence["trade_signals"] = EvidenceDoc(
                    ref=f"firestore:trade_signals/{doc_id or '<unknown>'}",
                    ts=ts or "",
                    data=dict(trade_signal_doc),
                )

    # (2.5) Firestore: execution reservation (optional context) at tenants/<tenant_id>/execution_reservations/<client_intent_id>
    # We do not import execution code; we only perform a direct Firestore READ when possible.
    if db is not None and iid:
        tenant_id = (os.getenv("EXEC_TENANT_ID") or os.getenv("TENANT_ID") or "").strip() or None
        if tenant_id:
            try:
                snap = (
                    db.collection("tenants")
                    .document(str(tenant_id))
                    .collection("execution_reservations")
                    .document(str(iid))
                    .get()
                )
                if getattr(snap, "exists", False):
                    d = _safe_to_dict(snap)
                    ts = _as_iso(_best_effort_dt_from_doc(d, "created_at", "created_at_iso", "expires_at", "released_at"))
                    evidence["execution_reservation"] = EvidenceDoc(
                        ref=f"firestore:tenants/{tenant_id}/execution_reservations/{iid}",
                        ts=ts or "",
                        data=d,
                    )
            except Exception as e:  # noqa: BLE001
                reason_codes.append(ReasonCode.FIRESTORE_READ_FAILED.value)
                warnings.append(f"execution_reservation_read_failed:{type(e).__name__}:{e}")
        else:
            warnings.append("execution_reservation_skipped_missing_tenant_id_env")

    # (3) Firestore: market regime (optional context)
    if db is not None:
        d, ev, rs = _read_market_regime(db)
        reason_codes.extend(rs)
        market_regime_doc = d
        evidence["market_regime"] = ev

    # (4) Firestore: shadowTradeHistory (user-scoped) — only when we can infer uid.
    if db is not None:
        uid = _best_effort_uid_from_docs(trading_signal=trading_signal_doc, trade_signal=trade_signal_doc)
        if uid and cid:
            d, ev, rs = _read_shadow_trade_by_uid_and_corr(db, uid=uid, correlation_id=cid, w=window)
            reason_codes.extend(rs)
            shadow_trade_doc = d
            evidence["shadowTradeHistory"] = ev
        elif cid:
            # We cannot safely enumerate users; keep this explicit.
            reason_codes.append(ReasonCode.NO_MATCHING_SHADOW_TRADE.value)
            if not uid:
                warnings.append("shadowTradeHistory_skipped_missing_uid_in_signal_docs")

    # (5) Structured events: no datastore assumed; accept caller-provided list.
    timeline: list[NormalizedEvent] = []
    if structured_events is None:
        reason_codes.append(ReasonCode.EVENTS_NOT_PROVIDED.value)
    else:
        filtered: list[NormalizedEvent] = []
        for raw in structured_events:
            if not isinstance(raw, Mapping):
                continue
            if not _event_match_ids(raw, signal_id=sid, correlation_id=cid, client_intent_id=iid):
                continue
            nev = _normalize_event(raw)
            # Optional time window filter.
            try:
                dt = parse_ts(nev.get("ts", "")) if nev.get("ts") else None
            except Exception:
                dt = None
            if dt is not None and not _within_window(dt, window):
                continue
            filtered.append(nev)

        if not filtered:
            reason_codes.append(ReasonCode.EVENTS_FILTERED_EMPTY.value)
        # Sort by timestamp.
        def _key(e: NormalizedEvent) -> str:
            return str(e.get("ts") or "")

        timeline = sorted(filtered, key=_key)

    # Resolve ids best-effort from evidence.
    resolved_signal_id = sid
    resolved_correlation_id = cid
    resolved_client_intent_id = iid

    # Prefer explicit fields from tradingSignals.
    if trading_signal_doc and not resolved_signal_id:
        resolved_signal_id = _clean_id(cast(str, trading_signal_doc.get("signal_id")))  # type: ignore[assignment]
    if trading_signal_doc and not resolved_correlation_id:
        resolved_correlation_id = _clean_id(cast(str, trading_signal_doc.get("correlation_id")))  # type: ignore[assignment]

    # Prefer nested `trade_signals.data.*` when available.
    if trade_signal_doc and isinstance(trade_signal_doc.get("data"), dict):
        d = cast(dict[str, Any], trade_signal_doc.get("data") or {})
        if not resolved_signal_id:
            resolved_signal_id = _clean_id(cast(str, d.get("signal_id") or d.get("signalId")))  # type: ignore[assignment]
        if not resolved_correlation_id:
            resolved_correlation_id = _clean_id(cast(str, d.get("correlation_id") or d.get("correlationId")))  # type: ignore[assignment]
        if not resolved_client_intent_id:
            resolved_client_intent_id = _clean_id(cast(str, d.get("client_intent_id") or d.get("clientIntentId")))  # type: ignore[assignment]

    decision = _extract_decision_from_any(trading_signal=trading_signal_doc, trade_signal=trade_signal_doc)

    # Final status: ok if we found any signal evidence.
    found_any_signal = bool(trading_signal_doc or trade_signal_doc)
    if not found_any_signal:
        reason_codes.append(ReasonCode.NO_MATCHING_SIGNAL.value)

    # Attach key evidence snapshots (raw) for consumers.
    evidence_payload: dict[str, Any] = {
        "tradingSignals": evidence.get("tradingSignals"),
        "trade_signals": evidence.get("trade_signals"),
        "shadowTradeHistory": evidence.get("shadowTradeHistory"),
        "market_regime": evidence.get("market_regime"),
        "execution_reservation": evidence.get("execution_reservation"),
    }

    # Ensure JSON-friendly dicts (TypedDicts can still carry non-serializable timestamps in nested raw data).
    # We do not mutate raw docs; we only provide them as-is under `data`.
    # Consumers that need strict JSON can post-process.
    def _compact_reason_codes(codes: Sequence[str]) -> list[str]:
        out = [str(c).strip() for c in codes if str(c).strip()]
        # Preserve order as "first occurrence wins", but drop duplicates.
        seen: set[str] = set()
        dedup: list[str] = []
        for c in out:
            if c in seen:
                continue
            seen.add(c)
            dedup.append(c)
        return dedup

    return ExplanationRecord(
        protocol="scalper_observer.v1",
        generated_at=_utc_now_iso(),
        query={
            "signal_id": sid,
            "correlation_id": cid,
            "client_intent_id": iid,
            "time_min": time_min,
            "time_max": time_max,
            "structured_events_provided": bool(structured_events),
        },
        signal_id=resolved_signal_id,
        correlation_id=resolved_correlation_id,
        client_intent_id=resolved_client_intent_id,
        decision=decision,
        ok=bool(found_any_signal) and (ReasonCode.FIRESTORE_CLIENT_UNAVAILABLE.value not in reason_codes),
        reason_codes=_compact_reason_codes(reason_codes),
        warnings=warnings,
        evidence=evidence_payload,
        timeline=timeline,
    )

