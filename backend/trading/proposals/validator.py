from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from backend.common.agent_mode import AgentMode, get_agent_mode

from .models import OrderProposal, ProposalAssetType, ProposalStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_symbol_allowlist(raw: str | None) -> Optional[set[str]]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return {p.strip().upper() for p in s.split(",") if p.strip()}


def get_symbol_allowlist() -> Optional[set[str]]:
    """
    Optional allowlist mechanism.

    If `SYMBOL_ALLOWLIST` is set (comma-separated), proposals must target one of those symbols.
    """
    return _parse_symbol_allowlist(os.getenv("SYMBOL_ALLOWLIST"))


@dataclass(frozen=True)
class ProposalValidationError(Exception):
    errors: list[str]

    def __str__(self) -> str:  # pragma: no cover
        return "OrderProposal validation failed: " + "; ".join(self.errors)


def validate_proposal(
    proposal: OrderProposal, *, symbol_allowlist: Optional[Iterable[str]] = None
) -> OrderProposal:
    """
    Fail-safe validation for order proposals.

    Behavior:
    - Raises ProposalValidationError on rejection.
    - May return a *normalized* proposal (e.g., enforcing requires_human_approval guard).
    """
    errors: list[str] = []

    # Enforce a conservative lifecycle status at creation time.
    if proposal.status != ProposalStatus.PROPOSED:
        errors.append(f"status must be PROPOSED on emit (got {proposal.status})")

    # Quantity must be positive (Pydantic also enforces gt=0, but keep fail-safe guard).
    if int(proposal.quantity) <= 0:
        errors.append("quantity must be > 0")

    # valid_until must be UTC-aware and not in the past
    vu: Optional[datetime] = None
    try:
        vu = proposal.constraints.valid_until_utc  # type: ignore[assignment,union-attr]
    except Exception:
        if isinstance(getattr(proposal, "constraints", None), dict):
            vu = proposal.constraints.get("valid_until_utc")  # type: ignore[union-attr]

    if not isinstance(vu, datetime):
        errors.append("constraints.valid_until_utc is required and must be a datetime")
    else:
        if vu.tzinfo is None or vu.tzinfo.utcoffset(vu) is None:
            errors.append("constraints.valid_until_utc must be timezone-aware (UTC)")
        elif vu <= _utc_now():
            errors.append("constraints.valid_until_utc is in the past")

    # Optional allowlist check
    allow = set(symbol_allowlist) if symbol_allowlist is not None else get_symbol_allowlist()
    if allow is not None and proposal.symbol.upper() not in {s.upper() for s in allow}:
        errors.append(f"symbol '{proposal.symbol}' not in allowlist")

    # OPTION contracts require option details
    if proposal.asset_type == ProposalAssetType.OPTION:
        opt = getattr(proposal, "option", None)
        if opt is None:
            errors.append("asset_type=OPTION requires option details")
        else:
            # Double-check required option fields exist (Pydantic already validates types).
            try:
                exp = opt.expiration  # type: ignore[attr-defined]
                right = opt.right  # type: ignore[attr-defined]
                strike = opt.strike  # type: ignore[attr-defined]
            except Exception:
                if isinstance(opt, dict):
                    exp = opt.get("expiration")
                    right = opt.get("right")
                    strike = opt.get("strike")
                else:
                    exp = right = strike = None
            if exp is None:
                errors.append("option.expiration is required")
            if right is None:
                errors.append("option.right is required")
            if strike is None:
                errors.append("option.strike is required")

    # Guard awareness:
    # Strategy workloads may propose in any mode, but should ALWAYS require human approval
    # unless an explicitly-authorized execution runtime consumes the proposals later.
    mode = get_agent_mode()
    force_approval = mode != AgentMode.LIVE
    normalized = proposal
    requires_approval = True
    try:
        requires_approval = bool(proposal.constraints.requires_human_approval)  # type: ignore[union-attr]
    except Exception:
        if isinstance(getattr(proposal, "constraints", None), dict):
            requires_approval = bool(proposal.constraints.get("requires_human_approval", True))  # type: ignore[union-attr]

    if force_approval and not requires_approval:
        normalized = proposal.model_copy(
            update={
                "constraints": proposal.constraints.model_copy(
                    update={"requires_human_approval": True}
                )
            }
        )

    if errors:
        # Mark rejected in-memory (do not mutate proposal); the caller can decide whether to emit rejection logs.
        raise ProposalValidationError(errors=errors)

    return normalized

