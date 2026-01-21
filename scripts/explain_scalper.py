#!/usr/bin/env python3
"""
Explain Scalper Observer (local CLI).

This is a READ-ONLY helper to inspect and explain "scalper" artifacts locally.

Supported selectors:
  - --signal-id <id>
  - --correlation-id <id>
  - --client-intent-id <id>
  - --last-minutes <n>

Data sources:
  - Default: Firestore (best-effort; requires ADC/emulator configuration)
  - Fallback: --input-events <path_to_jsonl> (newline-delimited JSON)

Safety:
  - No writes
  - No execution/broker code imports
  - Must NOT require EXEC_GUARD_UNLOCK
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


# Ensure repo root is importable (so `import backend...` works when invoked as a script).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ----------------------------
# Utilities (safe + stdlib)
# ----------------------------

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "private_key",
    "authorization",
}


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k).strip().lower()
            if ks in _SECRET_KEYS or "secret" in ks or "token" in ks or "password" in ks:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(v) for v in obj)
    return obj


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _parse_iso8601(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    txt = str(s).strip()
    if not txt:
        return None
    # tolerate Z suffix
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _coalesce(*vals: Any) -> Any:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _event_ts(event: dict[str, Any]) -> Optional[datetime]:
    # Prefer explicit timestamp-like fields used across this repo.
    return _parse_iso8601(
        _coalesce(
            event.get("timestamp"),
            event.get("created_at_iso"),
            event.get("ts"),
            event.get("log_ts"),
            (event.get("payload") or {}).get("ts") if isinstance(event.get("payload"), dict) else None,
        )
    )


def _safe_str(v: Any) -> str:
    return str(v).strip()


def _first_str(d: dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        if k not in d:
            continue
        s = str(d.get(k) or "").strip()
        if s:
            return s
    return None


def _extract_ids(event: dict[str, Any]) -> dict[str, Optional[str]]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    md = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        md = dict(md)
        md.update(payload.get("metadata") or {})

    signal_id = (
        _first_str(event, ("signal_id", "signalId", "id"))
        or _first_str(payload, ("signal_id", "signalId", "id"))
        or _first_str(md, ("signal_id", "signalId", "id"))
    )
    correlation_id = (
        _first_str(event, ("correlation_id", "correlationId", "trace_id", "traceId"))
        or _first_str(payload, ("correlation_id", "correlationId", "trace_id", "traceId"))
        or _first_str(md, ("correlation_id", "correlationId", "trace_id", "traceId"))
    )
    client_intent_id = (
        _first_str(event, ("client_intent_id", "clientIntentId", "idempotency_key", "intent_id", "intentId"))
        or _first_str(payload, ("client_intent_id", "clientIntentId", "idempotency_key", "intent_id", "intentId"))
        or _first_str(md, ("client_intent_id", "clientIntentId", "idempotency_key", "intent_id", "intentId"))
    )
    return {"signal_id": signal_id, "correlation_id": correlation_id, "client_intent_id": client_intent_id}


# ----------------------------
# Input events (JSONL)
# ----------------------------


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as e:  # noqa: BLE001
                raise SystemExit(f"ERROR: failed to parse JSON on line {i} of {path}: {type(e).__name__}: {e}") from e
            if not isinstance(obj, dict):
                continue
            out.append(obj)
    return out


# ----------------------------
# Firestore (best-effort read-only)
# ----------------------------


def _get_firestore_client(project_id: Optional[str] = None):
    # Import lazily so this script still runs without firebase-admin installed/configured.
    from backend.persistence.firebase_client import get_firestore_client  # noqa: WPS433

    return get_firestore_client(project_id=project_id)


def _fs_get_trading_signal(db: Any, signal_id: str) -> Optional[dict[str, Any]]:
    snap = db.collection("tradingSignals").document(str(signal_id)).get()
    if not getattr(snap, "exists", False):
        return None
    data = snap.to_dict() or {}
    data.setdefault("signal_id", str(signal_id))
    return data


def _fs_query_trading_signals_by_correlation(db: Any, correlation_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    try:
        from google.cloud import firestore  # noqa: WPS433

        q = (
            db.collection("tradingSignals")
            .where("correlation_id", "==", str(correlation_id))
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(int(limit))
        )
    except Exception:
        q = db.collection("tradingSignals").where("correlation_id", "==", str(correlation_id)).limit(int(limit))
    out: list[dict[str, Any]] = []
    for doc in q.stream():
        d = doc.to_dict() or {}
        d.setdefault("signal_id", d.get("signal_id") or doc.id)
        out.append(d)
    return out


def _fs_query_trading_signals_since(db: Any, since_utc: datetime, *, limit: int = 20) -> list[dict[str, Any]]:
    # This query may require indexes; keep it best-effort.
    try:
        from google.cloud import firestore  # noqa: WPS433

        q = (
            db.collection("tradingSignals")
            .where("timestamp", ">=", since_utc)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(int(limit))
        )
    except Exception:
        q = db.collection("tradingSignals").where("timestamp", ">=", since_utc).limit(int(limit))

    out: list[dict[str, Any]] = []
    for doc in q.stream():
        d = doc.to_dict() or {}
        d.setdefault("signal_id", d.get("signal_id") or doc.id)
        out.append(d)
    return out


def _fs_query_collection_group(db: Any, group: str, where_field: str, where_value: str, *, limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    q = db.collection_group(str(group)).where(str(where_field), "==", str(where_value)).limit(int(limit))
    for doc in q.stream():
        d = doc.to_dict() or {}
        d["_path"] = getattr(doc.reference, "path", None)
        out.append(d)
    return out


# ----------------------------
# Explanation model
# ----------------------------


@dataclass(frozen=True)
class ExplainQuery:
    signal_id: Optional[str] = None
    correlation_id: Optional[str] = None
    client_intent_id: Optional[str] = None
    last_minutes: Optional[int] = None


def _pick_latest(items: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not items:
        return None

    def key_fn(d: dict[str, Any]) -> tuple[int, str]:
        dt = _event_ts(d)
        if dt is None:
            return (0, "")
        return (1, dt.isoformat())

    return sorted(items, key=key_fn, reverse=True)[0]


def _format_signal_summary(sig: dict[str, Any]) -> str:
    ids = _extract_ids(sig)
    strategy = _safe_str(sig.get("strategy_name") or sig.get("strategy") or "unknown_strategy")
    symbol = _safe_str(sig.get("symbol") or "UNKNOWN")
    action = _safe_str(sig.get("action") or sig.get("signal") or "UNKNOWN")
    did_trade = sig.get("did_trade")
    ts = _event_ts(sig)
    ts_s = ts.isoformat() if ts else _safe_str(sig.get("timestamp") or sig.get("created_at_iso") or sig.get("ts") or "unknown_time")
    reason = _safe_str(sig.get("reason") or (sig.get("signal_payload") or {}).get("reason") or "")

    extras: list[str] = []
    payload = sig.get("signal_payload") if isinstance(sig.get("signal_payload"), dict) else {}
    for k in ("confidence", "sentiment_score", "net_delta", "abs_delta", "threshold", "delta_status", "gex_status", "gex_value"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if v is not None:
            extras.append(f"{k}={v}")

    parts = [
        f"{strategy}: {action} {symbol}",
        f"ts={ts_s}",
        f"did_trade={did_trade}" if did_trade is not None else None,
        f"signal_id={ids.get('signal_id')}" if ids.get("signal_id") else None,
        f"correlation_id={ids.get('correlation_id')}" if ids.get("correlation_id") else None,
    ]
    parts = [p for p in parts if p]
    if extras:
        parts.append("metrics: " + ", ".join(extras))
    if reason:
        parts.append("reason: " + reason)
    return " | ".join(parts)


def _matches_query(event: dict[str, Any], q: ExplainQuery, *, since_utc: Optional[datetime] = None) -> bool:
    ids = _extract_ids(event)
    if q.signal_id and ids.get("signal_id") == q.signal_id:
        return True
    if q.correlation_id and ids.get("correlation_id") == q.correlation_id:
        return True
    if q.client_intent_id and ids.get("client_intent_id") == q.client_intent_id:
        return True
    if since_utc is not None:
        ts = _event_ts(event)
        if ts and ts >= since_utc:
            return True
    return False


def _explain_from_events(events: list[dict[str, Any]], q: ExplainQuery) -> dict[str, Any]:
    since_utc = None
    if q.last_minutes is not None:
        since_utc = datetime.now(timezone.utc) - timedelta(minutes=int(q.last_minutes))

    matched = [e for e in events if _matches_query(e, q, since_utc=since_utc)]
    # Prefer actual tradingSignals-like docs when present.
    signals = [e for e in matched if isinstance(e.get("action"), str) and isinstance(e.get("symbol"), str)]
    best_signal = _pick_latest(signals) or _pick_latest(matched)

    summary = _format_signal_summary(best_signal) if best_signal else "No matching events found."
    return {
        "query": {
            "signal_id": q.signal_id,
            "correlation_id": q.correlation_id,
            "client_intent_id": q.client_intent_id,
            "last_minutes": q.last_minutes,
            "source": "input-events",
        },
        "summary": summary,
        "matched_count": len(matched),
        "signal": _redact(best_signal) if best_signal else None,
        "evidence": [_redact(e) for e in matched[:50]],
    }


def _explain_from_firestore(db: Any, q: ExplainQuery, *, tenant_id: Optional[str] = None) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    related: dict[str, Any] = {"execution_reservations": [], "paper_orders": []}

    if q.signal_id:
        sig = _fs_get_trading_signal(db, q.signal_id)
        if sig:
            signals = [sig]
            # Enrich with correlation_id if present
            ids = _extract_ids(sig)
            if ids.get("correlation_id") and not q.correlation_id:
                q = ExplainQuery(
                    signal_id=q.signal_id,
                    correlation_id=ids.get("correlation_id"),
                    client_intent_id=q.client_intent_id,
                    last_minutes=q.last_minutes,
                )
    elif q.correlation_id:
        signals = _fs_query_trading_signals_by_correlation(db, q.correlation_id)
    elif q.last_minutes is not None:
        since = datetime.now(timezone.utc) - timedelta(minutes=int(q.last_minutes))
        signals = _fs_query_trading_signals_since(db, since)

    # Related docs (best-effort): join on correlation_id or explicit client_intent_id.
    corr = q.correlation_id
    if corr:
        try:
            related["paper_orders"] = _fs_query_collection_group(
                db, "paper_orders", "correlation_id", corr, limit=20
            )
        except Exception:
            related["paper_orders"] = []

    if q.client_intent_id:
        cid = q.client_intent_id
        # execution_reservations are keyed by client_intent_id (doc id) and also store the field.
        if tenant_id:
            try:
                snap = (
                    db.collection("tenants")
                    .document(str(tenant_id))
                    .collection("execution_reservations")
                    .document(str(cid))
                    .get()
                )
                if getattr(snap, "exists", False):
                    d = snap.to_dict() or {}
                    d["_path"] = f"tenants/{tenant_id}/execution_reservations/{cid}"
                    related["execution_reservations"] = [d]
            except Exception:
                pass
        else:
            try:
                related["execution_reservations"] = _fs_query_collection_group(
                    db, "execution_reservations", "client_intent_id", cid, limit=20
                )
            except Exception:
                related["execution_reservations"] = []

        # paper_orders may include idempotency_key (when the idempotent insert path is used)
        try:
            po = _fs_query_collection_group(db, "paper_orders", "idempotency_key", cid, limit=20)
        except Exception:
            po = []
        if po:
            related["paper_orders"] = list(related.get("paper_orders") or []) + po

    best_signal = _pick_latest(signals)
    summary = _format_signal_summary(best_signal) if best_signal else "No matching Firestore artifacts found."

    return {
        "query": {
            "signal_id": q.signal_id,
            "correlation_id": q.correlation_id,
            "client_intent_id": q.client_intent_id,
            "last_minutes": q.last_minutes,
            "tenant_id": tenant_id,
            "source": "firestore",
        },
        "summary": summary,
        "signals_count": len(signals),
        "signal": _redact(best_signal) if best_signal else None,
        "related": _redact(related),
        "evidence": _redact({"signals": signals[:50], "related": related}),
    }


# ----------------------------
# CLI
# ----------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Explain scalper observer artifacts (read-only).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--signal-id", dest="signal_id", help="Trading signal document id")
    g.add_argument("--correlation-id", dest="correlation_id", help="Correlation id for stitching")
    g.add_argument("--client-intent-id", dest="client_intent_id", help="Execution client_intent_id / idempotency key")
    g.add_argument("--last-minutes", dest="last_minutes", type=int, help="Explain most recent scalper signals in last N minutes")
    p.add_argument("--input-events", dest="input_events", help="Path to JSONL of structured events (fallback when Firestore isn't configured)")
    p.add_argument("--json", dest="json_out", action="store_true", help="Print JSON output")
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Optional Firestore/Firebase project id (else uses FIREBASE_PROJECT_ID/ADC)",
    )
    p.add_argument(
        "--tenant-id",
        dest="tenant_id",
        default=None,
        help="Optional tenant id to resolve tenant-scoped docs (helps for --client-intent-id)",
    )
    return p


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])

    q = ExplainQuery(
        signal_id=args.signal_id,
        correlation_id=args.correlation_id,
        client_intent_id=args.client_intent_id,
        last_minutes=args.last_minutes,
    )

    # If Firestore isn't configured, users can provide input-events.
    if args.input_events:
        events = _load_jsonl(Path(args.input_events))
        result = _explain_from_events(events, q)
    else:
        try:
            db = _get_firestore_client(project_id=args.project_id)
        except Exception as e:  # noqa: BLE001
            msg = (
                "ERROR: Firestore is not configured/available for this environment.\n"
                f"Details: {type(e).__name__}: {e}\n"
                "Fix: configure ADC (e.g. `gcloud auth application-default login`) and set FIREBASE_PROJECT_ID, "
                "or run with FIRESTORE_EMULATOR_HOST, or provide --input-events <path_to_jsonl>."
            )
            if args.json_out:
                sys.stdout.write(
                    _json_dumps(
                        {
                            "query": {
                                "signal_id": q.signal_id,
                                "correlation_id": q.correlation_id,
                                "client_intent_id": q.client_intent_id,
                                "last_minutes": q.last_minutes,
                                "source": "firestore",
                            },
                            "error": msg,
                        }
                    )
                    + "\n"
                )
                return 2
            sys.stderr.write(msg + "\n")
            return 2

        result = _explain_from_firestore(db, q, tenant_id=args.tenant_id)

    if args.json_out:
        sys.stdout.write(_json_dumps(result) + "\n")
        return 0

    # Human output (concise)
    sys.stdout.write(result.get("summary", "No summary.") + "\n")
    # Provide a tiny hint when this is a broad selector.
    if q.last_minutes is not None:
        sys.stdout.write(f"(matched signals: {result.get('signals_count', 0)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

