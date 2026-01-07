from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import OrderProposal, ProposalStatus
from .validator import ProposalValidationError, validate_proposal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).isoformat()


def _json_line(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


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
    """
    Best-effort recursive redaction for audit artifacts.

    Only redacts values based on key names (never logs environment variables).
    """
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
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


def _intent_log(intent_type: str, **fields: Any) -> None:
    """
    Cloud-friendly JSON log line to stdout.
    """
    payload = {
        "event_type": "intent",
        "intent_type": intent_type,
        "severity": fields.pop("severity", "INFO"),
        "log_ts": _ts(),
        **fields,
    }
    payload.setdefault("ts", payload["log_ts"])
    print(_json_line(payload), flush=True)


def _audit_root() -> Path:
    return Path(os.getenv("AUDIT_ARTIFACTS_DIR") or "audit_artifacts")


def _proposal_audit_path(now: Optional[datetime] = None) -> Path:
    d = (now or _utc_now()).date().isoformat()
    return _audit_root() / "proposals" / d / "proposals.ndjson"


@dataclass
class _LifecycleEntry:
    proposal: OrderProposal
    created_ts: datetime


class InMemoryProposalLifecycle:
    """
    Optional scaffolding: supersede and expire proposals locally/in-memory.

    This is intentionally lightweight and does not require a database.
    """

    def __init__(self, *, supersede_window_s: int = 30):
        self.supersede_window_s = max(0, int(supersede_window_s))
        self._latest_by_key: dict[Tuple[str, str, str], _LifecycleEntry] = {}
        self._by_id: dict[str, OrderProposal] = {}

    def _key(self, p: OrderProposal) -> Tuple[str, str, str]:
        # strategy + symbol + contract key (option details if present; otherwise asset_type)
        if p.option is not None:
            ck = f"{p.symbol}:{p.option.expiration}:{p.option.right}:{p.option.strike}"
        else:
            ck = f"{p.symbol}:{p.asset_type}"
        return (p.strategy_name, p.symbol, ck)

    def register(self, p: OrderProposal) -> None:
        key = self._key(p)
        now = _utc_now()
        prev = self._latest_by_key.get(key)
        if prev is not None:
            age = (now - prev.created_ts).total_seconds()
            if age <= self.supersede_window_s:
                # Mark previous proposal as SUPERSEDED in-memory (no persistence required).
                self._by_id[str(prev.proposal.proposal_id)] = prev.proposal.model_copy(
                    update={"status": ProposalStatus.SUPERSEDED}
                )
                _intent_log(
                    "order_proposal",
                    event="superseded",
                    superseded_proposal_id=str(prev.proposal.proposal_id),
                    new_proposal_id=str(p.proposal_id),
                    strategy_name=p.strategy_name,
                    symbol=p.symbol,
                )
        self._latest_by_key[key] = _LifecycleEntry(proposal=p, created_ts=now)
        self._by_id[str(p.proposal_id)] = p

    def expire(self) -> None:
        now = _utc_now()
        for pid, p in list(self._by_id.items()):
            if p.status in {ProposalStatus.PROPOSED} and p.constraints.valid_until_utc <= now:
                self._by_id[pid] = p.model_copy(update={"status": ProposalStatus.EXPIRED})
                _intent_log(
                    "order_proposal",
                    event="expired",
                    proposal_id=str(p.proposal_id),
                    strategy_name=p.strategy_name,
                    symbol=p.symbol,
                )


_LIFECYCLE = InMemoryProposalLifecycle(
    supersede_window_s=int(os.getenv("PROPOSAL_SUPERSEDE_WINDOW_S") or "30")
)


def emit_proposal(proposal: OrderProposal) -> None:
    """
    Emit a validated order proposal:
    - logs an intent event (summary only)
    - writes the full proposal to append-only NDJSON under audit_artifacts/

    Safety: this function NEVER executes orders.
    """
    try:
        p = validate_proposal(proposal)
    except ProposalValidationError as e:
        _intent_log(
            "order_proposal",
            event="rejected",
            proposal_id=str(proposal.proposal_id),
            strategy_name=proposal.strategy_name,
            symbol=proposal.symbol,
            errors=e.errors,
            severity="WARNING",
        )
        return

    option_summary = None
    if p.option is not None:
        option_summary = {
            "expiration": p.option.expiration.isoformat(),
            "right": p.option.right.value,
            "strike": p.option.strike,
            "contract_symbol": p.option.contract_symbol,
        }

    _intent_log(
        "order_proposal",
        event="proposed",
        proposal_id=str(p.proposal_id),
        strategy_name=p.strategy_name,
        symbol=p.symbol,
        asset_type=p.asset_type.value,
        option=option_summary,
        side=p.side.value,
        quantity=p.quantity,
        limit_price=p.limit_price,
        time_in_force=p.time_in_force.value,
        valid_until_utc=p.constraints.valid_until_utc.isoformat(),
        requires_human_approval=p.constraints.requires_human_approval,
    )

    # Register in lifecycle store (optional scaffolding)
    _LIFECYCLE.register(p)
    _LIFECYCLE.expire()

    # Write full proposal as NDJSON (redacted-safe)
    try:
        audit_path = _proposal_audit_path(p.created_at_utc)
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        # Pydantic v2: model_dump(mode="json") produces JSON-safe primitives.
        raw = (
            p.model_dump(mode="json")  # type: ignore[attr-defined]
            if hasattr(p, "model_dump")
            else p.dict()  # pragma: no cover
        )
        # Redact indicators and any nested secrets before persistence.
        raw_rationale = raw.get("rationale") or {}
        if isinstance(raw_rationale, dict):
            raw_rationale["indicators"] = _redact(raw_rationale.get("indicators") or {})
            raw["rationale"] = raw_rationale

        with audit_path.open("a", encoding="utf-8") as f:
            f.write(_json_line(raw) + "\n")
    except Exception as e:
        # Filesystem may be read-only in some containers; fall back to stdout.
        _intent_log(
            "order_proposal",
            event="audit_write_failed",
            proposal_id=str(p.proposal_id),
            error=str(e),
            severity="WARNING",
        )
        # Fallback: emit the full proposal JSON line to stdout (still redacted).
        try:
            fallback = (
                p.model_dump(mode="json")  # type: ignore[attr-defined]
                if hasattr(p, "model_dump")
                else p.dict()  # pragma: no cover
            )
            fb_rationale = fallback.get("rationale") or {}
            if isinstance(fb_rationale, dict):
                fb_rationale["indicators"] = _redact(fb_rationale.get("indicators") or {})
                fallback["rationale"] = fb_rationale
            print(_json_line({"event_type": "order_proposal_fallback", **fallback}), flush=True)
        except Exception:
            return

