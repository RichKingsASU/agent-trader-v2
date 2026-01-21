from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def test_execution_decider_consumes_order_proposal_contract_fields() -> None:
    """
    Contract test: the execution decider must consume the shared OrderProposal schema
    (not an ad-hoc flattened dict).
    """
    try:
        from backend.trading.execution.decider import decide_execution
        from backend.trading.execution.models import SafetySnapshot
        from backend.trading.proposals.models import (
            OrderProposal,
            ProposalAssetType,
            ProposalConstraints,
            ProposalRationale,
            ProposalSide,
        )
    except Exception as e:  # pragma: no cover
        pytest.xfail(f"Execution decider contract depends on optional pydantic models: {type(e).__name__}: {e}")

    now = datetime.now(timezone.utc)
    p = OrderProposal(
        repo_id="repo",
        agent_name="strategy-engine",
        strategy_name="test_strategy",
        correlation_id="corr",
        symbol="SPY",
        asset_type=ProposalAssetType.EQUITY,
        side=ProposalSide.BUY,
        quantity=1,
        rationale=ProposalRationale(short_reason="test", indicators={}),
        constraints=ProposalConstraints(
            valid_until_utc=now + timedelta(minutes=5),
            requires_human_approval=True,
        ),
    )
    safety = SafetySnapshot(
        kill_switch=False,
        marketdata_fresh=True,
        marketdata_last_ts=now.isoformat(),
        agent_mode="OBSERVE",
    )
    d = decide_execution(proposal=p, safety=safety, agent_name="execution-agent", agent_role="execution", now=now)
    assert d.decision == "REJECT"
    assert "requires_human_approval" in d.reject_reason_codes

