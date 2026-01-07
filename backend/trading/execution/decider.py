from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.trading.execution.models import ExecutionDecision, SafetySnapshot


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Support common Z suffix.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _compact_recommended_order(proposal: dict[str, Any]) -> dict[str, Any]:
    """
    Produce a compact, audit-friendly order summary.

    - Prefers proposal["order"] if present and dict-like
    - Otherwise uses an allowlist of common order fields
    """
    order = proposal.get("order")
    if isinstance(order, dict):
        return dict(order)

    allow = [
        "symbol",
        "side",
        "qty",
        "quantity",
        "order_type",
        "type",
        "time_in_force",
        "tif",
        "limit_price",
        "stop_price",
        "asset_class",
        "broker_account_id",
        "strategy_id",
    ]
    out: dict[str, Any] = {}
    for k in allow:
        if k in proposal:
            out[k] = proposal.get(k)
    if not out:
        # Fall back to minimal traceability only (do NOT embed entire proposal).
        for k in ("proposal_id", "id", "correlation_id", "run_id"):
            if k in proposal:
                out[k] = proposal.get(k)
    return out


def decide_execution(
    *,
    proposal: dict[str, Any],
    safety: SafetySnapshot,
    agent_name: str,
    agent_role: str,
    now: datetime | None = None,
) -> ExecutionDecision:
    """
    Deterministic, safe stub decision logic.

    Posture: REJECT by default unless explicitly allowed.
    """
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    proposal_id = str(proposal.get("proposal_id") or proposal.get("id") or "").strip()
    correlation_id = (
        str(proposal.get("correlation_id") or proposal.get("run_id") or proposal.get("trace_id") or "").strip()
        or None
    )

    reject: list[str] = []

    if not proposal_id:
        reject.append("proposal_missing_id")
        proposal_id = "missing_proposal_id"

    # Rule: kill switch => reject
    if safety.kill_switch:
        reject.append("kill_switch_enabled")

    # Rule: marketdata stale/missing => reject
    if not safety.marketdata_fresh:
        reject.append("marketdata_stale_or_missing")

    # Rule: requires_human_approval => reject (default True)
    rha = proposal.get("requires_human_approval")
    requires_human_approval = True if rha is None else bool(rha)
    if requires_human_approval:
        reject.append("requires_human_approval")

    # Rule: proposal valid_until expired => reject (missing/unparseable => reject)
    valid_until_raw = proposal.get("valid_until_utc") or proposal.get("valid_until") or proposal.get("valid_until_ts")
    valid_until_dt = _coerce_dt(valid_until_raw)
    if valid_until_dt is None:
        reject.append("proposal_valid_until_missing_or_unparseable")
    else:
        if valid_until_dt < now_dt:
            reject.append("proposal_expired")

    decision = "REJECT" if reject else "APPROVE"

    notes = str(proposal.get("notes") or "").strip()
    if not notes and decision == "APPROVE":
        notes = "Approved by deterministic stub (NO ORDER WILL BE PLACED)."
    if not notes and decision == "REJECT":
        notes = "Rejected by deterministic stub."

    return ExecutionDecision(
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        agent_name=str(agent_name),
        agent_role=str(agent_role),
        decision=decision,  # type: ignore[arg-type]
        reject_reason_codes=reject,
        notes=notes,
        recommended_order=_compact_recommended_order(proposal),
        safety_snapshot=safety,
    )

