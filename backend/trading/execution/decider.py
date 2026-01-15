from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from backend.trading.execution.models import ExecutionDecision, SafetySnapshot
from backend.trading.proposals.models import OrderProposal


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


def _compact_recommended_order(proposal: OrderProposal | Mapping[str, Any]) -> dict[str, Any]:
    """
    Produce a compact, audit-friendly order summary.

    Uses a stable subset of the proposal contract fields only.
    """
    if isinstance(proposal, Mapping):
        p = proposal
        order = p.get("order") if isinstance(p.get("order"), Mapping) else {}
        symbol = order.get("symbol") if isinstance(order.get("symbol"), str) else None
        side = order.get("side") if isinstance(order.get("side"), str) else None
        qty = order.get("qty")
        try:
            qty_i = int(qty) if qty is not None else 0
        except Exception:
            qty_i = 0
        valid_until = _coerce_dt(p.get("valid_until_utc")) or datetime.now(timezone.utc)
        return {
            "proposal_id": str(p.get("proposal_id") or ""),
            "correlation_id": str(p.get("correlation_id") or "").strip() or None,
            "strategy_name": str(p.get("strategy_name") or "").strip() or None,
            "symbol": symbol,
            "asset_type": str(p.get("asset_type") or "equity"),
            "side": (str(side).lower() if side is not None else None),
            "quantity": qty_i,
            "limit_price": p.get("limit_price"),
            "time_in_force": str(p.get("time_in_force") or "day"),
            "valid_until_utc": valid_until.astimezone(timezone.utc).isoformat(),
            "requires_human_approval": bool(p.get("requires_human_approval", True)),
        }

    return {
        "proposal_id": str(proposal.proposal_id),
        "correlation_id": proposal.correlation_id,
        "strategy_name": proposal.strategy_name,
        "symbol": proposal.symbol,
        "asset_type": proposal.asset_type.value,
        "side": proposal.side.value,
        "quantity": int(proposal.quantity),
        "limit_price": proposal.limit_price,
        "time_in_force": proposal.time_in_force.value,
        "valid_until_utc": proposal.constraints.valid_until_utc.isoformat(),
        "requires_human_approval": bool(proposal.constraints.requires_human_approval),
    }


def decide_execution(
    *,
    proposal: OrderProposal | Mapping[str, Any],
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

    if isinstance(proposal, Mapping):
        proposal_id = str(proposal.get("proposal_id") or "")
        correlation_id = str(proposal.get("correlation_id") or "").strip() or None
        requires_human_approval = bool(proposal.get("requires_human_approval", True))
        valid_until_dt = _coerce_dt(proposal.get("valid_until_utc"))
        # Missing/unparseable => reject.
        if valid_until_dt is None:
            valid_until_dt = now_dt.replace(microsecond=0)  # expired
    else:
        proposal_id = str(proposal.proposal_id)
        correlation_id = str(proposal.correlation_id or "").strip() or None
        requires_human_approval = bool(proposal.constraints.requires_human_approval)
        valid_until_dt = proposal.constraints.valid_until_utc

    reject: list[str] = []

    # Rule: kill switch => reject
    if safety.kill_switch:
        reject.append("kill_switch_enabled")

    # Rule: marketdata stale/missing => reject
    if not safety.marketdata_fresh:
        reject.append("marketdata_stale_or_missing")

    # Rule: requires_human_approval => reject (default True)
    if requires_human_approval:
        reject.append("requires_human_approval")

    # Rule: proposal valid_until expired => reject (missing/unparseable => reject)
    if valid_until_dt.astimezone(timezone.utc) < now_dt:
        reject.append("proposal_expired")

    decision = "REJECT" if reject else "APPROVE"

    notes = ""
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

