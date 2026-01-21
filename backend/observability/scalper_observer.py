"""
Scalper Observer (AgentTrader v2) — READ-ONLY explanation module

Safety guarantees (absolute):
- READ-ONLY: This module performs Firestore reads only (document gets / queries).
- NO broker calls: does not import or call any broker SDKs.
- NO execution logic: does not place orders, size orders, or trigger execution flows.
- NO config writes: does not write to Firestore, local files, or any config stores.
- NO Firestore writes: never calls set/create/update/delete/batch writes.
- NO env var changes: does not mutate process environment.
- NO kill switch interaction: does not read/flip kill switch state from control planes; it only
  infers kill-switch effects from already-recorded signal/execution documents.

Primary entrypoint:
  explain_scalper_decision(input: Mapping[str, Any]) -> dict[str, Any]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional, Sequence

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry

logger = logging.getLogger(__name__)

Decision = Literal["BUY", "SELL", "HOLD", "CLOSE_ALL", "NO_OP"]


@dataclass(frozen=True)
class _SignalRecord:
    collection: str
    doc_id: str
    doc: dict[str, Any]

    def event_time(self) -> Optional[datetime]:
        """
        Best-effort ordering key across legacy/new schemas.
        """
        for k in ("eventTime", "timestamp", "created_at", "createdAt", "publishedAt", "producedAt"):
            dt = _coerce_dt(self.doc.get(k))
            if dt is not None:
                return dt
        # `trade_signals` payload is nested.
        data = self.doc.get("data")
        if isinstance(data, dict):
            for k in ("eventTime", "timestamp", "decisionAt", "createdAt", "updatedAt", "publishedAt", "producedAt"):
                dt = _coerce_dt(data.get(k))
                if dt is not None:
                    return dt
        return None


def _coerce_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _upper_action(value: Any) -> str:
    s = "" if value is None else str(value).strip().upper()
    return s


def _extract_payload(doc: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize different signal record shapes into a single dict used for inference.
    """
    if not isinstance(doc, dict):
        return {}
    # New: cloudrun_consumer materialization into `trade_signals` uses {"data": <payload>}.
    data = doc.get("data")
    if isinstance(data, dict) and data:
        return data
    # Legacy: `tradingSignals` uses `signal_payload` for structured data.
    payload = doc.get("signal_payload")
    if isinstance(payload, dict) and payload:
        # Keep the top-level keys too; some important fields are not nested.
        merged = dict(doc)
        merged.setdefault("signal_payload", payload)
        merged.update(payload)
        return merged
    return dict(doc)


def _extract_execution_events(payload: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Best-effort extraction of execution attempt/completion artifacts from a trade signal payload.

    Expected/accepted shapes:
    - payload.execution.attempt / payload.execution.completed
    - payload["execution.attempt"] / payload["execution.completed"]
    - payload.execution_attempt / payload.execution_completed
    - payload.events[] entries with event_type == execution.attempt|execution.completed
    """
    if not isinstance(payload, Mapping):
        return None, None

    execution = payload.get("execution")
    if isinstance(execution, Mapping):
        att = execution.get("attempt")
        comp = execution.get("completed")
        return (dict(att) if isinstance(att, Mapping) else None, dict(comp) if isinstance(comp, Mapping) else None)

    att = payload.get("execution.attempt")
    comp = payload.get("execution.completed")
    if isinstance(att, Mapping) or isinstance(comp, Mapping):
        return (dict(att) if isinstance(att, Mapping) else None, dict(comp) if isinstance(comp, Mapping) else None)

    att = payload.get("execution_attempt")
    comp = payload.get("execution_completed")
    if isinstance(att, Mapping) or isinstance(comp, Mapping):
        return (dict(att) if isinstance(att, Mapping) else None, dict(comp) if isinstance(comp, Mapping) else None)

    events = payload.get("events")
    if isinstance(events, Sequence):
        attempt_ev = None
        completed_ev = None
        for ev in events:
            if not isinstance(ev, Mapping):
                continue
            et = _upper_action(ev.get("event_type") or ev.get("eventType") or ev.get("type"))
            if et == "EXECUTION.ATTEMPT" and attempt_ev is None:
                attempt_ev = dict(ev)
            if et == "EXECUTION.COMPLETED" and completed_ev is None:
                completed_ev = dict(ev)
        return attempt_ev, completed_ev

    return None, None


def _infer_safety_state(payload: Mapping[str, Any], attempt: dict[str, Any] | None, completed: dict[str, Any] | None) -> dict[str, Optional[bool]]:
    """
    Infer shadow_mode/execution_enabled/kill_switch ONLY from already-recorded docs.
    Never queries any control-plane kill switch config.
    """
    shadow_mode: Optional[bool] = None
    execution_enabled: Optional[bool] = None
    kill_switch: Optional[bool] = None

    # Common shapes: safety_state / safety / flags
    for key in ("safety_state", "safetyState", "safety", "flags"):
        ss = payload.get(key)
        if not isinstance(ss, Mapping):
            continue
        shadow_mode = shadow_mode if shadow_mode is not None else _as_bool(ss.get("shadow_mode") or ss.get("shadowMode") or ss.get("is_shadow_mode"))
        execution_enabled = execution_enabled if execution_enabled is not None else _as_bool(
            ss.get("execution_enabled") or ss.get("executionEnabled") or ss.get("trading_enabled") or ss.get("tradingEnabled")
        )
        kill_switch = kill_switch if kill_switch is not None else _as_bool(ss.get("kill_switch") or ss.get("killSwitch") or ss.get("execution_halted"))

    # Execution attempt/completed often include mode (shadow/live) and/or kill-switch rejection.
    for ev in (attempt or {}, completed or {}):
        if shadow_mode is None:
            mode = str(ev.get("mode") or "").strip().lower()
            if mode == "shadow":
                shadow_mode = True
            elif mode in {"live", "paper"}:
                shadow_mode = False

        if kill_switch is None:
            # Typical API error payloads / reason codes
            err = str(ev.get("error") or ev.get("error_code") or ev.get("code") or "").strip().lower()
            if "kill_switch" in err or "kill-switch" in err:
                kill_switch = True
            detail = ev.get("detail")
            if isinstance(detail, Mapping):
                e = str(detail.get("error") or "").strip().lower()
                if "kill_switch" in e:
                    kill_switch = True
            reject = ev.get("reject_reason_codes") or ev.get("rejectReasons") or ev.get("reasons")
            if isinstance(reject, Sequence) and any("kill_switch" in str(x).lower() for x in reject):
                kill_switch = True

    return {"shadow_mode": shadow_mode, "execution_enabled": execution_enabled, "kill_switch": kill_switch}


def _detect_missing_delta(payload: Mapping[str, Any]) -> bool:
    for k in ("delta", "net_delta", "netDelta", "net_delta_before", "netDeltaBefore"):
        if k in payload and payload.get(k) is not None:
            return False
    # Nested "greeks"
    greeks = payload.get("greeks")
    if isinstance(greeks, Mapping) and greeks.get("delta") is not None:
        return False
    return True


def _detect_missing_price(payload: Mapping[str, Any]) -> bool:
    for k in ("price", "underlying_price", "underlyingPrice", "mid", "bid", "ask"):
        if k in payload and payload.get(k) is not None:
            return False
    return True


def _detect_rate_limit(payload: Mapping[str, Any], attempt: dict[str, Any] | None, completed: dict[str, Any] | None) -> bool:
    # Direct flags
    for k in ("rate_limited", "rateLimitHit", "rate_limit_hit", "rateLimit", "rate_limit"):
        b = _as_bool(payload.get(k))
        if b is True:
            return True
    # Reason codes
    for src in (payload, attempt or {}, completed or {}):
        rc = src.get("reason_codes") or src.get("reasonCodes") or src.get("reject_reason_codes") or src.get("rejectReasons")
        if isinstance(rc, Sequence) and any("rate" in str(x).lower() and "limit" in str(x).lower() for x in rc):
            return True
        msg = str(src.get("error") or src.get("message") or "").lower()
        if "too many requests" in msg or "rate limit" in msg or "ratelimit" in msg:
            return True
        status = src.get("status_code") or src.get("http_status") or src.get("httpStatus")
        try:
            if int(status) == 429:
                return True
        except Exception:
            pass
    return False


def _detect_threshold_not_crossed(payload: Mapping[str, Any]) -> bool:
    """
    Heuristic for gamma scalper-style logic:
    - if abs(delta/net_delta_before/net_delta) <= threshold/hedging_threshold => threshold not crossed.
    """
    # Candidate values (use first available)
    delta_val = None
    for k in ("net_delta_before", "netDeltaBefore", "net_delta", "netDelta", "delta"):
        delta_val = _as_float(payload.get(k))
        if delta_val is not None:
            break

    thr = None
    for k in ("hedging_threshold", "hedgingThreshold", "threshold", "delta_threshold", "deltaThreshold"):
        thr = _as_float(payload.get(k))
        if thr is not None:
            break

    if delta_val is None or thr is None:
        return False
    try:
        return abs(float(delta_val)) <= float(thr)
    except Exception:
        return False


def _decision_from_payload(payload: Mapping[str, Any], completed: dict[str, Any] | None) -> Decision:
    # Prefer what actually completed (if present) over the raw signal action.
    if isinstance(completed, dict):
        side = completed.get("side") or completed.get("action")
        act = _upper_action(side)
        if act in {"BUY", "SELL"}:
            return act  # type: ignore[return-value]
        mode = str(completed.get("mode") or "").strip().lower()
        # "paper"/"shadow" can still have BUY/SELL; don't infer action from mode.

    action = _upper_action(payload.get("action") or payload.get("side") or payload.get("decision"))
    if action in {"BUY", "SELL", "HOLD", "CLOSE_ALL"}:
        return action  # type: ignore[return-value]
    if action in {"FLAT", "NONE", "NOOP", "NO_OP"}:
        return "NO_OP"
    # signalType / intent hint
    st = _upper_action(payload.get("signalType") or payload.get("signal_type") or payload.get("type"))
    if st in {"EXIT", "CLOSE", "CLOSE_ALL", "FLATTEN"}:
        return "CLOSE_ALL"
    return "NO_OP"


def _build_human_explanation(*, decision: Decision, reason_codes: Sequence[str], payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if decision in {"BUY", "SELL"}:
        parts.append(f"Signal indicated {decision}.")
    elif decision == "HOLD":
        parts.append("Signal indicated HOLD (no position change).")
    elif decision == "CLOSE_ALL":
        parts.append("Signal indicated CLOSE_ALL (flatten exposure).")
    else:
        parts.append("No executable action was taken.")

    # Reason code narration (keep it short and operator-friendly).
    rc = set(reason_codes)
    if "KILL_SWITCH_ACTIVE" in rc:
        parts.append("Execution was blocked because the kill switch was active.")
    if "SHADOW_MODE" in rc:
        parts.append("System was in shadow mode (simulation), so live execution was not performed.")
    if "RATE_LIMIT_HIT" in rc:
        parts.append("Execution was suppressed due to a rate limit.")
    if "THRESHOLD_NOT_CROSSED" in rc:
        # Provide helpful numeric context when available.
        delta = None
        for k in ("net_delta_before", "net_delta", "delta"):
            delta = payload.get(k)
            if delta is not None:
                break
        thr = payload.get("hedging_threshold") or payload.get("threshold")
        if delta is not None and thr is not None:
            parts.append(f"Delta/threshold condition was not met (delta={delta}, threshold={thr}).")
        else:
            parts.append("Delta/threshold condition was not met.")
    if "MISSING_DELTA" in rc:
        parts.append("Required delta inputs were missing/unavailable.")
    if "MISSING_PRICE" in rc:
        parts.append("Required price inputs were missing/unavailable.")

    # If we have no recognized reasons, still return something useful.
    if len(parts) <= 1 and reason_codes:
        parts.append(f"Reason codes: {', '.join(reason_codes)}")
    return " ".join(p for p in parts if p)


def _read_doc(*, db: Any, collection: str, doc_id: str) -> Optional[_SignalRecord]:
    ref = db.collection(str(collection)).document(str(doc_id))
    snap = with_firestore_retry(lambda: ref.get())
    if not getattr(snap, "exists", False):
        return None
    try:
        d = snap.to_dict() or {}
    except Exception:
        d = {}
    return _SignalRecord(collection=str(collection), doc_id=str(doc_id), doc=d if isinstance(d, dict) else {})


def _query_signals_by_correlation_id(
    *, db: Any, collection: str, correlation_id: str, limit: int = 25
) -> list[_SignalRecord]:
    """
    Best-effort query; supports a few common field placements.
    """
    corr = str(correlation_id or "").strip()
    if not corr:
        return []

    candidates = [
        "correlation_id",
        "correlationId",
        "data.correlation_id",
        "data.correlationId",
        "signal_payload.correlation_id",
        "signal_payload.correlationId",
    ]
    out: list[_SignalRecord] = []
    seen: set[str] = set()
    for field in candidates:
        try:
            q = db.collection(str(collection)).where(field, "==", corr).limit(int(limit))
            snaps = with_firestore_retry(lambda: list(q.stream()))
        except Exception:
            continue
        for s in snaps:
            try:
                doc_id = str(s.id)
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                d = s.to_dict() or {}
                if isinstance(d, dict):
                    out.append(_SignalRecord(collection=str(collection), doc_id=doc_id, doc=d))
            except Exception:
                continue
    return out


def _query_signals_by_time_range(
    *,
    db: Any,
    collection: str,
    time_field: str,
    start: Optional[datetime],
    end: Optional[datetime],
    limit: int = 50,
) -> list[_SignalRecord]:
    if start is None and end is None:
        return []
    try:
        q = db.collection(str(collection)).order_by(time_field)
        if start is not None:
            q = q.where(time_field, ">=", start)
        if end is not None:
            q = q.where(time_field, "<=", end)
        q = q.limit(int(limit))
        snaps = with_firestore_retry(lambda: list(q.stream()))
    except Exception:
        return []
    out: list[_SignalRecord] = []
    for s in snaps:
        try:
            d = s.to_dict() or {}
            if isinstance(d, dict):
                out.append(_SignalRecord(collection=str(collection), doc_id=str(s.id), doc=d))
        except Exception:
            continue
    return out


def explain_scalper_decision(input: Mapping[str, Any]) -> dict[str, Any]:
    """
    Explain why a scalper signal did (or did not) result in execution.

    Args:
        input: Mapping that may include:
          - signal_id (preferred)
          - correlation_id
          - start_time / end_time (ISO string or datetime)

    Returns:
        Structured explanation object:
          {
            signal_id,
            decision: BUY | SELL | HOLD | CLOSE_ALL | NO_OP,
            reason_codes: [...],
            human_explanation: "...",
            safety_state: { shadow_mode, execution_enabled, kill_switch }
          }
    """
    if not isinstance(input, Mapping):
        raise TypeError("explain_scalper_decision expects a mapping-like input")

    signal_id = str(input.get("signal_id") or input.get("signalId") or "").strip() or None
    correlation_id = str(input.get("correlation_id") or input.get("correlationId") or "").strip() or None
    start = _coerce_dt(input.get("start_time") or input.get("startTime") or input.get("from"))
    end = _coerce_dt(input.get("end_time") or input.get("endTime") or input.get("to"))

    db = get_firestore_client()

    # 1) Direct lookup is preferred.
    records: list[_SignalRecord] = []
    if signal_id:
        for col in ("trade_signals", "tradingSignals"):
            rec = _read_doc(db=db, collection=col, doc_id=signal_id)
            if rec is not None:
                records.append(rec)

    # 2) Otherwise, correlation_id query.
    if (not records) and correlation_id:
        for col in ("trade_signals", "tradingSignals"):
            records.extend(_query_signals_by_correlation_id(db=db, collection=col, correlation_id=correlation_id))

    # 3) Otherwise, time range query (best-effort; may require Firestore composite indexes in some deployments).
    if (not records) and (start is not None or end is not None):
        records.extend(_query_signals_by_time_range(db=db, collection="trade_signals", time_field="eventTime", start=start, end=end))
        records.extend(_query_signals_by_time_range(db=db, collection="tradingSignals", time_field="timestamp", start=start, end=end))

    if not records:
        # Return a stable shape even when nothing matches.
        return {
            "signal_id": signal_id,
            "decision": "NO_OP",
            "reason_codes": ["SIGNAL_NOT_FOUND"],
            "human_explanation": "No matching signal record was found in Firestore for the provided identifiers/time range.",
            "safety_state": {"shadow_mode": None, "execution_enabled": None, "kill_switch": None},
        }

    # Prefer the newest record (and prefer `trade_signals` when ties).
    def _rk(r: _SignalRecord) -> tuple[int, int, str]:
        t = r.event_time()
        ts = int(t.timestamp()) if isinstance(t, datetime) else 0
        prefer_new = 1 if r.collection == "trade_signals" else 0
        return (ts, prefer_new, r.doc_id)

    rec = sorted(records, key=_rk, reverse=True)[0]
    doc = rec.doc
    payload = _extract_payload(doc)

    attempt, completed = _extract_execution_events(payload)
    safety_state = _infer_safety_state(payload, attempt, completed)

    desired = _decision_from_payload(payload, completed)

    # Detect reasons.
    reason_codes: list[str] = []

    # Kill switch / shadow mode (inferred from recorded docs only)
    if safety_state.get("kill_switch") is True:
        reason_codes.append("KILL_SWITCH_ACTIVE")
    if safety_state.get("shadow_mode") is True:
        reason_codes.append("SHADOW_MODE")

    # Data quality
    if _detect_missing_delta(payload):
        reason_codes.append("MISSING_DELTA")
    if _detect_missing_price(payload):
        reason_codes.append("MISSING_PRICE")

    # Rate limiting
    if _detect_rate_limit(payload, attempt, completed):
        reason_codes.append("RATE_LIMIT_HIT")

    # Threshold logic
    if _detect_threshold_not_crossed(payload):
        reason_codes.append("THRESHOLD_NOT_CROSSED")

    # Final decision: if the signal wanted to trade but there is no completion, classify as NO_OP.
    did_execute = False
    if isinstance(completed, dict) and completed:
        did_execute = True
    if _as_bool(doc.get("did_trade")) is True:
        did_execute = True
    if _as_bool(payload.get("did_trade")) is True:
        did_execute = True

    decision: Decision
    if desired in {"BUY", "SELL", "CLOSE_ALL"} and not did_execute:
        decision = "NO_OP"
    else:
        decision = desired

    # Prefer explicit signal_id identity fields when present.
    resolved_signal_id = (
        str(payload.get("signal_id") or payload.get("signalId") or doc.get("signal_id") or doc.get("docId") or rec.doc_id).strip()
        or rec.doc_id
    )

    human = _build_human_explanation(decision=decision, reason_codes=reason_codes, payload=payload)

    return {
        "signal_id": resolved_signal_id,
        "decision": decision,
        "reason_codes": reason_codes,
        "human_explanation": human,
        "safety_state": {
            "shadow_mode": safety_state.get("shadow_mode"),
            "execution_enabled": safety_state.get("execution_enabled"),
            "kill_switch": safety_state.get("kill_switch"),
        },
    }

