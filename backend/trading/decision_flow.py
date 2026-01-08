from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.trading.agent_intent.models import AgentIntent, IntentAssetType, IntentSide
from backend.trading.proposals.models import (
    OrderProposal,
    ProposalAssetType,
    ProposalConstraints,
    ProposalRationale,
    ProposalSide,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def intent_to_order_proposal(*, intent: AgentIntent, quantity: int) -> Optional[OrderProposal]:
    """
    Centralized conversion: AgentIntent (no capital) → OrderProposal (sized).

    The allocator decides `quantity`. Callers MUST NOT pass agent-derived sizing.
    """
    if intent.side == IntentSide.FLAT:
        return None
    if quantity <= 0:
        return None

    side = ProposalSide.BUY if intent.side == IntentSide.BUY else ProposalSide.SELL
    asset_type = (
        ProposalAssetType.EQUITY
        if intent.asset_type == IntentAssetType.EQUITY
        else ProposalAssetType.OPTION
        if intent.asset_type == IntentAssetType.OPTION
        else ProposalAssetType.FUTURE
    )

    # Option details are currently not carried end-to-end for intents in this repo.
    # Keep as None until option routing is wired to the allocator.
    return OrderProposal(
        created_at_utc=_utc_now(),
        repo_id=intent.repo_id,
        agent_name=intent.agent_name,
        strategy_name=intent.strategy_name,
        strategy_version=intent.strategy_version,
        correlation_id=intent.correlation_id,
        symbol=intent.symbol,
        asset_type=asset_type,
        option=None,
        side=side,
        quantity=int(quantity),
        limit_price=(intent.constraints.limit_price if intent.constraints.order_type == "limit" else None),
        rationale=ProposalRationale(
            short_reason=intent.rationale.short_reason,
            indicators=intent.rationale.indicators,
        ),
        constraints=ProposalConstraints(
            valid_until_utc=intent.constraints.valid_until_utc,
            requires_human_approval=bool(intent.constraints.requires_human_approval),
        ),
    )

