"""
READ-ONLY Scalper Observer — explanation module

Objective:
- Explain why a signal was emitted (or not)
- Explain why execution was blocked or simulated

Hard safety constraints:
- READ ONLY (Firestore + logs)
- NO broker calls
- NO execution logic
- NO writes except explanation records (explicitly requested via write_explanation=True)

Correlates (best-effort):
- Firestore: `tradingSignals` (legacy) and `trade_signals` (cloudrun_consumer materialization)
- Firestore: `users/{uid}/shadowTradeHistory` (when uid can be inferred from recorded artifacts)
- Logs: `execution.attempt` / `execution.completed` structured logs (Cloud Logging), when available

Output:
Human-readable explanation JSON with at least:
- net_delta
- threshold
- GEX / macro regime
- safety gates triggered
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

try:
    # In production this provides retries for transient Firestore issues.
    from backend.persistence.firestore_retry import with_firestore_retry
except Exception:  # pragma: no cover
    # Keep module importable in minimal/unit-test environments where google libs aren't installed.
    def with_firestore_retry(fn):  # type: ignore[no-redef]
        return fn()

logger = logging.getLogger(__name__)

Decision = Literal["BUY", "SELL", "HOLD", "CLOSE_ALL", "NO_OP"]


# ---- shared tiny helpers (stdlib-only) ----


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


def _clean_text(v: Any, *, max_len: int = 2000) -> str:
    try:
        s = "" if v is None else str(v)
    except Exception:
        s = ""
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _upper_action(value: Any) -> str:
    return _clean_text(value, max_len=64).upper()


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in mapping and mapping.get(k) is not None:
            return mapping.get(k)
    return None


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
        merged = dict(doc)
        merged.setdefault("signal_payload", payload)
        merged.update(payload)
        return merged
    return dict(doc)


def _extract_execution_events(payload: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Best-effort extraction of execution attempt/completion artifacts from a payload.
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


def _decision_from_payload(payload: Mapping[str, Any], completed: dict[str, Any] | None) -> Decision:
    # Prefer what actually completed (if present) over the raw signal action.
    if isinstance(completed, dict):
        side = completed.get("side") or completed.get("action")
        act = _upper_action(side)
        if act in {"BUY", "SELL"}:
            return act  # type: ignore[return-value]

    action = _upper_action(payload.get("action") or payload.get("side") or payload.get("decision"))
    if action in {"BUY", "SELL", "HOLD", "CLOSE_ALL"}:
        return action  # type: ignore[return-value]
    if action in {"FLAT", "NONE", "NOOP", "NO_OP"}:
        return "NO_OP"
    st = _upper_action(payload.get("signalType") or payload.get("signal_type") or payload.get("type"))
    if st in {"EXIT", "CLOSE", "CLOSE_ALL", "FLATTEN"}:
        return "CLOSE_ALL"
    return "NO_OP"


def _infer_safety_gates(
    *,
    payload: Mapping[str, Any],
    attempt: Mapping[str, Any] | None,
    completed: Mapping[str, Any] | None,
    risk_allowed: Optional[bool],
    threshold_not_crossed: bool,
    rate_limited: bool,
) -> list[str]:
    """
    Return stable gate codes (operator-friendly).
    """
    gates: list[str] = []

    # Shadow/live mode (from recorded artifacts only)
    mode = None
    for ev in (completed or {}, attempt or {}):
        m = str(ev.get("mode") or "").strip().lower()
        if m:
            mode = m
            break
    if mode == "shadow":
        gates.append("SHADOW_MODE")

    # Kill switch / global halt (inferred from recorded errors/reason codes)
    for ev in (attempt or {}, completed or {}, payload):
        msg = str(ev.get("error") or ev.get("message") or ev.get("detail") or "").lower()
        if "kill_switch" in msg or "kill-switch" in msg or "kill switch" in msg:
            gates.append("KILL_SWITCH_ACTIVE")
            break
        code = str(ev.get("error_code") or ev.get("code") or "").lower()
        if "kill_switch" in code or "kill-switch" in code:
            gates.append("KILL_SWITCH_ACTIVE")
            break

    if risk_allowed is False:
        gates.append("RISK_DENIED")

    if rate_limited:
        gates.append("RATE_LIMIT_HIT")

    if threshold_not_crossed:
        gates.append("THRESHOLD_NOT_CROSSED")

    return sorted(set(gates))


def _detect_rate_limit(payload: Mapping[str, Any], attempt: Mapping[str, Any] | None, completed: Mapping[str, Any] | None) -> bool:
    for k in ("rate_limited", "rateLimitHit", "rate_limit_hit", "rateLimit", "rate_limit"):
        b = _as_bool(payload.get(k))
        if b is True:
            return True
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


def _detect_threshold_not_crossed(net_delta: Optional[float], threshold: Optional[float]) -> bool:
    if net_delta is None or threshold is None:
        return False
    try:
        return abs(float(net_delta)) <= float(threshold)
    except Exception:
        return False


def _extract_net_delta(payload: Mapping[str, Any]) -> Optional[float]:
    # Prefer explicit pre-trade net delta keys used by gamma scalper intents.
    for k in ("net_delta", "netDelta", "net_delta_before", "netDeltaBefore", "delta"):
        v = _as_float(payload.get(k))
        if v is not None:
            return v
    greeks = payload.get("greeks")
    if isinstance(greeks, Mapping):
        v = _as_float(greeks.get("delta"))
        if v is not None:
            return v
    # Common intent metadata shape
    md = payload.get("metadata")
    if isinstance(md, Mapping):
        v = _as_float(md.get("net_delta_before") or md.get("netDeltaBefore") or md.get("net_delta"))
        if v is not None:
            return v
    return None


def _extract_threshold(payload: Mapping[str, Any]) -> Optional[float]:
    for k in ("hedging_threshold", "hedgingThreshold", "threshold", "delta_threshold", "deltaThreshold"):
        v = _as_float(payload.get(k))
        if v is not None:
            return v
    md = payload.get("metadata")
    if isinstance(md, Mapping):
        v = _as_float(md.get("hedging_threshold") or md.get("threshold") or md.get("delta_threshold"))
        if v is not None:
            return v
    return None


def _extract_gex(payload: Mapping[str, Any]) -> Optional[float]:
    for k in ("gex_value", "gexValue", "net_gex", "netGex"):
        v = _as_float(payload.get(k))
        if v is not None:
            return v
    md = payload.get("metadata")
    if isinstance(md, Mapping):
        v = _as_float(md.get("gex_value") or md.get("net_gex"))
        if v is not None:
            return v
    return None


def _extract_macro_flag(payload: Mapping[str, Any]) -> Optional[bool]:
    for k in ("macro_event_active", "macroEventActive", "macro_event_detected", "macroEventDetected"):
        b = _as_bool(payload.get(k))
        if b is not None:
            return b
    md = payload.get("metadata")
    if isinstance(md, Mapping):
        b = _as_bool(md.get("macro_event_active") or md.get("macroEventActive"))
        if b is not None:
            return b
    return None


# ---- Firestore models / reads ----


@dataclass(frozen=True)
class _SignalRecord:
    collection: str
    doc_id: str
    doc: dict[str, Any]

    def event_time(self) -> Optional[datetime]:
        for k in ("eventTime", "timestamp", "created_at", "createdAt", "publishedAt", "producedAt"):
            dt = _coerce_dt(self.doc.get(k))
            if dt is not None:
                return dt
        data = self.doc.get("data")
        if isinstance(data, dict):
            for k in ("eventTime", "timestamp", "decisionAt", "createdAt", "updatedAt", "publishedAt", "producedAt"):
                dt = _coerce_dt(data.get(k))
                if dt is not None:
                    return dt
        return None


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


def _query_by_correlation_id(*, db: Any, collection: str, correlation_id: str, limit: int = 25) -> list[_SignalRecord]:
    corr = str(correlation_id or "").strip()
    if not corr:
        return []
    candidates = [
        # common top-level
        "correlation_id",
        "correlationId",
        # trade_signals.data.*
        "data.correlation_id",
        "data.correlationId",
        # tradingSignals.signal_payload.*
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
                sid = str(s.id)
                if sid in seen:
                    continue
                seen.add(sid)
                d = s.to_dict() or {}
                if isinstance(d, dict):
                    out.append(_SignalRecord(collection=str(collection), doc_id=sid, doc=d))
            except Exception:
                continue
    return out


def _read_market_regime(*, db: Any) -> dict[str, Any] | None:
    try:
        snap = with_firestore_retry(lambda: db.collection("systemStatus").document("market_regime").get())
    except Exception:
        return None
    if not getattr(snap, "exists", False):
        return None
    try:
        d = snap.to_dict() or {}
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _market_regime_summary(regime_doc: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(regime_doc, Mapping):
        return None
    spy = regime_doc.get("spy")
    spy_net_gex = None
    if isinstance(spy, Mapping):
        spy_net_gex = _as_float(spy.get("net_gex"))
    return {
        "macro_event_detected": _as_bool(regime_doc.get("macro_event_detected")),
        "macro_event_status": regime_doc.get("macro_event_status"),
        "stop_loss_multiplier": _as_float(regime_doc.get("stop_loss_multiplier")),
        "position_size_multiplier": _as_float(regime_doc.get("position_size_multiplier")),
        "spy_net_gex": spy_net_gex,
        "last_updated": (
            _coerce_dt(regime_doc.get("last_updated"))
            or _coerce_dt(regime_doc.get("macro_event_time"))
            or _coerce_dt(regime_doc.get("updatedAt"))
        ),
    }


# ---- Logs (Cloud Logging) best-effort reader ----


class _CloudLoggingReader:
    """
    Best-effort Cloud Logging reader for structured JSON logs.

    If google-cloud-logging is unavailable or credentials are missing, this reader
    returns no entries (fails closed to Firestore-only correlation).
    """

    def __init__(self, *, project_id: str | None = None) -> None:
        self._project_id = (str(project_id).strip() if project_id else None) or None

    def list_execution_events(
        self,
        *,
        correlation_id: str,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        cid = str(correlation_id or "").strip()
        if not cid:
            return []

        try:
            from google.cloud import logging as cloud_logging  # type: ignore
        except Exception:
            return []

        # Narrow time window to keep queries cheap and reduce accidental matches.
        start = start_time or (datetime.now(timezone.utc) - timedelta(minutes=15))
        end = end_time or (start + timedelta(minutes=30))
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)

        # Filter on jsonPayload.correlation_id (our JsonLogFormatter key).
        # Also accept http.request correlation ids if present, but we primarily want execution.*
        time_filter = f'timestamp>="{start.isoformat()}" AND timestamp<="{end.isoformat()}"'
        corr_filter = f'jsonPayload.correlation_id="{cid}"'
        event_filter = (
            "("
            'jsonPayload.event_type="execution.attempt" OR '
            'jsonPayload.event_type="execution.completed" OR '
            'jsonPayload.event_type="risk.trade_check.allowed" OR '
            'jsonPayload.event_type="risk.trade_check.denied"'
            ")"
        )
        flt = f"{time_filter} AND {corr_filter} AND {event_filter}"

        try:
            client = cloud_logging.Client(project=self._project_id) if self._project_id else cloud_logging.Client()
            entries_iter = client.list_entries(filter_=flt, order_by=cloud_logging.DESCENDING, page_size=int(limit))
            entries = []
            for e in entries_iter:
                # cloud logging entry payload is usually a dict-like for jsonPayload
                payload = None
                try:
                    payload = e.payload  # type: ignore[attr-defined]
                except Exception:
                    payload = None
                if isinstance(payload, Mapping):
                    d = dict(payload)
                    # Attach a timestamp for ordering if available.
                    try:
                        ts = getattr(e, "timestamp", None)
                        d["_log_timestamp"] = _coerce_dt(ts).isoformat() if _coerce_dt(ts) else None
                    except Exception:
                        d["_log_timestamp"] = None
                    entries.append(d)
                if len(entries) >= int(limit):
                    break
            return entries
        except Exception:
            return []


def _pick_best_event(entries: Iterable[Mapping[str, Any]], event_type: str) -> dict[str, Any] | None:
    """
    Pick the newest matching event by embedded timestamp fields.
    """
    best = None
    best_ts = None
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        if str(e.get("event_type") or "") != event_type:
            continue
        ts = _coerce_dt(e.get("timestamp") or e.get("_log_timestamp"))
        if best is None or (ts is not None and (best_ts is None or ts > best_ts)):
            best = dict(e)
            best_ts = ts
    return best


# ---- Shadow trade correlation ----


def _find_shadow_trade(
    *,
    db: Any,
    uid: str,
    correlation_id: str | None,
    symbol: str | None,
    side: str | None,
    center_time: datetime | None,
    window_s: int = 600,
    limit: int = 25,
) -> dict[str, Any] | None:
    """
    Best-effort lookup in `users/{uid}/shadowTradeHistory`.

    Primary correlation:
    - `idempotency_key == correlation_id` (common when idempotency defaults to corr)

    Fallback:
    - Scan recent documents around center_time and match (symbol, side) heuristically.
    """
    u = str(uid or "").strip()
    if not u:
        return None

    corr = str(correlation_id or "").strip() or None
    sym = str(symbol or "").strip().upper() or None
    sd = str(side or "").strip().lower() or None
    t0 = center_time.astimezone(timezone.utc) if isinstance(center_time, datetime) else None

    col = db.collection("users").document(u).collection("shadowTradeHistory")

    # 1) Direct idempotency key correlation.
    if corr:
        try:
            q = col.where("idempotency_key", "==", corr).limit(int(limit))
            snaps = with_firestore_retry(lambda: list(q.stream()))
            for s in snaps:
                try:
                    d = s.to_dict() or {}
                except Exception:
                    continue
                if isinstance(d, dict):
                    return d
        except Exception:
            pass

    # 2) Time+symbol heuristic scan (bounded).
    if t0 is None:
        return None
    start = t0 - timedelta(seconds=int(window_s))
    end = t0 + timedelta(seconds=int(window_s))

    candidates: list[dict[str, Any]] = []
    try:
        q = col.order_by("created_at").where("created_at", ">=", start).where("created_at", "<=", end).limit(int(limit))
        snaps = with_firestore_retry(lambda: list(q.stream()))
    except Exception:
        snaps = []

    for s in snaps:
        try:
            d = s.to_dict() or {}
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        candidates.append(d)

    if not candidates:
        return None

    def score(d: Mapping[str, Any]) -> int:
        sc = 0
        if sym and str(d.get("symbol") or "").strip().upper() == sym:
            sc += 2
        if sd and str(d.get("side") or "").strip().lower() == sd:
            sc += 1
        # Prefer closer in time if we have created_at_iso.
        ct = _coerce_dt(d.get("created_at_iso") or d.get("created_at"))
        if ct is not None:
            dt_s = abs(int((ct - t0).total_seconds()))
            if dt_s <= 60:
                sc += 2
            elif dt_s <= 180:
                sc += 1
        return sc

    best = sorted(candidates, key=score, reverse=True)[0]
    return dict(best) if best else None


# ---- public API ----


class ScalperObserver:
    def __init__(self, *, db: Any | None = None, log_reader: Any | None = None) -> None:
        if db is None:
            # Lazy import keeps this module importable in minimal test environments
            # where firebase_admin is not installed.
            from backend.persistence.firebase_client import get_firestore_client  # noqa: WPS433

            db = get_firestore_client()
        self._db = db
        self._log_reader = log_reader or _CloudLoggingReader()

    def explain(
        self,
        *,
        signal_id: str | None = None,
        correlation_id: str | None = None,
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        write_explanation: bool = False,
        explanation_collection: str = "scalper_explanations",
    ) -> dict[str, Any]:
        """
        Produce a human-readable explanation JSON and optionally persist it as an explanation record.
        """
        sid = str(signal_id or "").strip() or None
        cid = str(correlation_id or "").strip() or None
        start = _coerce_dt(start_time)
        end = _coerce_dt(end_time)

        # ---- 1) Load signal record(s) ----
        records: list[_SignalRecord] = []
        if sid:
            for col in ("trade_signals", "tradingSignals"):
                rec = _read_doc(db=self._db, collection=col, doc_id=sid)
                if rec is not None:
                    records.append(rec)

        if (not records) and cid:
            for col in ("trade_signals", "tradingSignals"):
                records.extend(_query_by_correlation_id(db=self._db, collection=col, correlation_id=cid))

        if not records:
            out = {
                "signal_id": sid,
                "correlation_id": cid,
                "net_delta": None,
                "threshold": None,
                "gex": None,
                "macro_regime": None,
                "safety_gates_triggered": ["SIGNAL_NOT_FOUND"],
                "human_explanation": "No matching signal record was found in Firestore for the provided identifiers/time range.",
            }
            if write_explanation:
                self._write_explanation_record(collection=explanation_collection, signal_id=sid or cid or None, explanation=out)
            return out

        def rk(r: _SignalRecord) -> tuple[int, int, str]:
            t = r.event_time()
            ts = int(t.timestamp()) if isinstance(t, datetime) else 0
            prefer_new = 1 if r.collection == "trade_signals" else 0
            return (ts, prefer_new, r.doc_id)

        rec = sorted(records, key=rk, reverse=True)[0]
        doc = rec.doc
        payload = _extract_payload(doc)
        event_time = rec.event_time()

        # Resolve correlation id from payload/doc if missing.
        if cid is None:
            cid = (
                str(
                    payload.get("correlation_id")
                    or payload.get("correlationId")
                    or doc.get("correlation_id")
                    or doc.get("correlationId")
                    or (doc.get("data") or {}).get("correlation_id")
                    if isinstance(doc.get("data"), dict)
                    else None
                ).strip()
                or None
            )

        # ---- 2) Extract execution attempt/completed from payload (embedded) ----
        embedded_attempt, embedded_completed = _extract_execution_events(payload)

        # ---- 3) Pull log-correlated execution events (best-effort) ----
        log_entries: list[dict[str, Any]] = []
        if cid:
            # If we have a signal event time, constrain log search to a small window around it.
            st = (event_time - timedelta(minutes=10)) if isinstance(event_time, datetime) else start
            en = (event_time + timedelta(minutes=20)) if isinstance(event_time, datetime) else end
            log_entries = self._log_reader.list_execution_events(  # type: ignore[attr-defined]
                correlation_id=cid,
                start_time=st,
                end_time=en,
                limit=50,
            )

        attempt_log = _pick_best_event(log_entries, "execution.attempt")
        completed_log = _pick_best_event(log_entries, "execution.completed")
        risk_allowed_log = _pick_best_event(log_entries, "risk.trade_check.allowed")
        risk_denied_log = _pick_best_event(log_entries, "risk.trade_check.denied")

        # Canonical attempt/completed: prefer logs (ground truth) over embedded.
        attempt = attempt_log or embedded_attempt
        completed = completed_log or embedded_completed

        # ---- 4) Compute requested numeric context ----
        net_delta = _extract_net_delta(payload)
        threshold = _extract_threshold(payload)
        threshold_not_crossed = _detect_threshold_not_crossed(net_delta, threshold)
        rate_limited = _detect_rate_limit(payload, attempt, completed)

        # ---- 5) Market regime context (read-only Firestore) ----
        market_regime_doc = _read_market_regime(db=self._db)
        market_regime = _market_regime_summary(market_regime_doc)

        gex_payload = _extract_gex(payload)
        gex_effective = gex_payload
        if gex_effective is None and isinstance(market_regime, Mapping):
            gex_effective = _as_float(market_regime.get("spy_net_gex"))

        macro_active = _extract_macro_flag(payload)
        if macro_active is None and isinstance(market_regime, Mapping):
            macro_active = _as_bool(market_regime.get("macro_event_detected"))

        # ---- 6) Risk context (recorded only) ----
        risk_allowed = None
        # Prefer explicit risk log events if present.
        if risk_allowed_log is not None:
            risk_allowed = True
        if risk_denied_log is not None:
            risk_allowed = False
        # Fallback: payload shapes sometimes include risk_allowed/riskAllowed.
        if risk_allowed is None:
            risk_allowed = _as_bool(payload.get("risk_allowed") or payload.get("riskAllowed"))

        # ---- 7) Shadow trade correlation (if we can infer uid) ----
        uid = None
        for src in (attempt_log or {}, completed_log or {}, payload, doc):
            if isinstance(src, Mapping):
                cand = src.get("uid") or src.get("user_id") or src.get("userId")
                if cand is not None and str(cand).strip():
                    uid = str(cand).strip()
                    break

        symbol = str(payload.get("symbol") or doc.get("symbol") or "").strip() or None
        side = str(payload.get("side") or payload.get("action") or "").strip() or None
        shadow_trade = None
        if uid:
            shadow_trade = _find_shadow_trade(
                db=self._db,
                uid=uid,
                correlation_id=cid,
                symbol=symbol,
                side=side,
                center_time=_coerce_dt((completed or {}).get("timestamp")) or event_time,
            )

        # ---- 8) Decision + narrative ----
        decision = _decision_from_payload(payload, completed)
        did_execute = bool(isinstance(completed, Mapping) and len(completed) > 0)
        if _as_bool(doc.get("did_trade")) is True or _as_bool(payload.get("did_trade")) is True:
            did_execute = True

        # If it wanted to trade but we have no execution completion, treat as NO_OP for explanation.
        if decision in {"BUY", "SELL", "CLOSE_ALL"} and not did_execute:
            decision_effective: Decision = "NO_OP"
        else:
            decision_effective = decision

        gates = _infer_safety_gates(
            payload=payload,
            attempt=attempt,
            completed=completed,
            risk_allowed=risk_allowed,
            threshold_not_crossed=threshold_not_crossed,
            rate_limited=rate_limited,
        )

        # Human-readable explanation: short, operator-friendly, numeric when available.
        parts: list[str] = []
        if decision in {"BUY", "SELL"}:
            parts.append(f"Signal indicated {decision}.")
        elif decision == "HOLD":
            parts.append("Signal indicated HOLD.")
        elif decision == "CLOSE_ALL":
            parts.append("Signal indicated CLOSE_ALL (flatten exposure).")
        else:
            parts.append("No executable action was indicated.")

        if net_delta is not None and threshold is not None:
            parts.append(f"Delta/threshold: net_delta={net_delta:.6g}, threshold={threshold:.6g}.")
        elif net_delta is not None:
            parts.append(f"Delta context: net_delta={net_delta:.6g} (threshold unavailable).")

        if gex_effective is not None:
            parts.append(f"GEX context: gex={gex_effective:.6g}.")
        if macro_active is True:
            status = (market_regime or {}).get("macro_event_status") if isinstance(market_regime, Mapping) else None
            parts.append(f"Macro regime: macro_event_active=true{f' ({status})' if status else ''}.")
        elif macro_active is False:
            parts.append("Macro regime: macro_event_active=false.")

        if decision_effective == "NO_OP" and decision in {"BUY", "SELL", "CLOSE_ALL"}:
            if gates:
                parts.append(f"Execution did not complete due to gates: {', '.join(gates)}.")
            else:
                parts.append("Execution did not complete; no explicit gate was recorded on the signal/log artifacts.")
        else:
            # Execution completed (or was a no-op signal)
            if isinstance(completed, Mapping) and completed.get("mode"):
                parts.append(f"Execution mode: {completed.get('mode')}.")
            elif isinstance(attempt, Mapping) and attempt.get("mode"):
                parts.append(f"Execution mode: {attempt.get('mode')}.")

        # Shadow trade details if present
        if isinstance(shadow_trade, Mapping):
            px = shadow_trade.get("entry_price")
            q = shadow_trade.get("quantity")
            parts.append(f"Shadow trade matched: qty={q}, entry_price={px}.")

        human = " ".join(p for p in parts if p)

        # Resolve stable signal id if embedded in payload/doc.
        resolved_signal_id = (
            str(payload.get("signal_id") or payload.get("signalId") or doc.get("signal_id") or doc.get("docId") or rec.doc_id).strip()
            or rec.doc_id
        )

        out: dict[str, Any] = {
            "signal_id": resolved_signal_id,
            "correlation_id": cid,
            "event_time": event_time.isoformat() if isinstance(event_time, datetime) else None,
            "decision": decision_effective,
            "net_delta": net_delta,
            "threshold": threshold,
            "gex": {
                "value": gex_effective,
                "source": ("payload" if gex_payload is not None else ("systemStatus/market_regime" if gex_effective is not None else None)),
            }
            if (gex_effective is not None)
            else None,
            "macro_regime": {
                "macro_event_active": macro_active,
                **(dict(market_regime) if isinstance(market_regime, Mapping) else {}),
            }
            if (macro_active is not None or market_regime is not None)
            else None,
            "safety_gates_triggered": gates,
            "execution": {
                "attempt": dict(attempt) if isinstance(attempt, Mapping) else None,
                "completed": dict(completed) if isinstance(completed, Mapping) else None,
                "logs_used": bool(attempt_log or completed_log or risk_allowed_log or risk_denied_log),
            },
            "shadow_trade": dict(shadow_trade) if isinstance(shadow_trade, Mapping) else None,
            "human_explanation": human,
        }

        if write_explanation:
            self._write_explanation_record(
                collection=explanation_collection,
                signal_id=resolved_signal_id,
                explanation=out,
            )

        return out

    def _write_explanation_record(self, *, collection: str, signal_id: str | None, explanation: Mapping[str, Any]) -> None:
        """
        The ONLY allowed write path: persist an explanation record.
        """
        doc_id = str(signal_id or "").strip() or None
        if doc_id is None:
            # Fall back to a deterministic-ish id to avoid generating large random IDs.
            doc_id = datetime.now(timezone.utc).strftime("explain_%Y%m%dT%H%M%SZ")

        try:
            from firebase_admin import firestore as fb_firestore  # type: ignore
        except Exception:
            fb_firestore = None  # type: ignore[assignment]

        record: dict[str, Any] = {
            "signal_id": doc_id,
            "created_at": (fb_firestore.SERVER_TIMESTAMP if fb_firestore is not None else datetime.now(timezone.utc)),
            "explanation": dict(explanation),
        }
        # Keep root fields queryable.
        for k in ("correlation_id", "decision", "event_time", "safety_gates_triggered"):
            if k in explanation:
                record[k] = explanation.get(k)

        ref = self._db.collection(str(collection)).document(doc_id)
        with_firestore_retry(lambda: ref.set(record, merge=True))


__all__ = ["ScalperObserver"]

