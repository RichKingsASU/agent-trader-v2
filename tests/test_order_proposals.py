from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

try:
    from backend.trading.proposals.emitter import emit_proposal
    from backend.trading.proposals.models import (
        OrderProposal,
        OptionRight,
        ProposalAssetType,
        ProposalConstraints,
        ProposalOption,
        ProposalRationale,
        ProposalSide,
    )
    from backend.trading.proposals.validator import ProposalValidationError, validate_proposal
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"Order proposal schemas depend on optional pydantic models: {type(e).__name__}: {e}",
        strict=False,
    )


def _mk_option_proposal(*, symbol: str = "SPY", secret_in_indicators: bool = False) -> OrderProposal:
    now = datetime.now(timezone.utc)
    indicators = {"sma": 1.0}
    if secret_in_indicators:
        indicators["api_key"] = "SHOULD_NOT_APPEAR"
        indicators["nested"] = {"token": "SHOULD_NOT_APPEAR"}

    return OrderProposal(
        created_at_utc=now,
        repo_id="RichKingsASU/agent-trader-v2",
        agent_name="pytest",
        strategy_name="test_strategy",
        strategy_version="0.0.0",
        correlation_id="corr",
        symbol=symbol,
        asset_type=ProposalAssetType.OPTION,
        option=ProposalOption(
            expiration=(now.date() + timedelta(days=7)),
            right=OptionRight.CALL,
            strike=500.0,
            contract_symbol=None,
        ),
        side=ProposalSide.BUY,
        quantity=1,
        limit_price=1.23,
        rationale=ProposalRationale(short_reason="test", indicators=indicators),
        constraints=ProposalConstraints(
            valid_until_utc=(now + timedelta(minutes=5)),
            requires_human_approval=True,
        ),
    )


def test_schema_defaults_and_types():
    p = _mk_option_proposal()
    assert p.proposal_id is not None
    assert str(p.proposal_id)
    assert p.created_at_utc.tzinfo is not None
    assert p.constraints.requires_human_approval is True
    assert p.time_in_force.value == "DAY"


def test_proposal_id_uniqueness():
    p1 = _mk_option_proposal()
    p2 = _mk_option_proposal()
    assert p1.proposal_id != p2.proposal_id


def test_validator_rejects_missing_option_fields():
    p = _mk_option_proposal()
    # Construct an invalid instance in a way that bypasses BaseModel field validation.
    if hasattr(OrderProposal, "model_construct"):
        bad = OrderProposal.model_construct(**{**p.model_dump(), "option": None})  # type: ignore[attr-defined]
    else:  # pragma: no cover (pydantic v1 fallback)
        bad = OrderProposal.construct(**{**p.dict(), "option": None})

    with pytest.raises(ProposalValidationError) as e:
        validate_proposal(bad)
    assert "asset_type=OPTION requires option details" in ";".join(e.value.errors)


def test_validator_rejects_past_valid_until():
    p = _mk_option_proposal()
    past = p.model_copy(
        update={
            "constraints": p.constraints.model_copy(
                update={"valid_until_utc": datetime.now(timezone.utc) - timedelta(seconds=1)}
            )
        }
    )
    with pytest.raises(ProposalValidationError) as e:
        validate_proposal(past)
    assert "constraints.valid_until_utc is in the past" in ";".join(e.value.errors)


def test_validator_respects_symbol_allowlist(monkeypatch):
    monkeypatch.setenv("SYMBOL_ALLOWLIST", "SPY,QQQ")
    p = _mk_option_proposal(symbol="AAPL")
    with pytest.raises(ProposalValidationError):
        validate_proposal(p)


def test_emitter_writes_ndjson_and_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_ARTIFACTS_DIR", str(tmp_path / "audit_artifacts"))
    p = _mk_option_proposal(secret_in_indicators=True)

    emit_proposal(p)

    out_path = (tmp_path / "audit_artifacts" / "proposals" / p.created_at_utc.date().isoformat() / "proposals.ndjson")
    assert out_path.exists()
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])

    # Ensure redaction happened (secret values should not appear).
    indicators = payload["rationale"]["indicators"]
    assert indicators["api_key"] == "***REDACTED***"
    assert indicators["nested"]["token"] == "***REDACTED***"
    assert "SHOULD_NOT_APPEAR" not in lines[0]

