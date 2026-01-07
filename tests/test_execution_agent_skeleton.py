from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.execution_agent.gating import enforce_startup_gate_or_exit
from backend.trading.execution.decider import decide_execution
from backend.trading.execution.models import SafetySnapshot


def test_gating_refuses_startup_when_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Clear gate vars to ensure fail-closed.
    for k in [
        "REPO_ID",
        "AGENT_NAME",
        "AGENT_ROLE",
        "AGENT_MODE",
        "EXECUTION_AGENT_ENABLED",
        "BROKER_EXECUTION_ENABLED",
    ]:
        monkeypatch.delenv(k, raising=False)

    with pytest.raises(SystemExit) as e:
        enforce_startup_gate_or_exit()

    assert int(getattr(e.value, "code", 1) or 1) != 0


def test_decision_rejects_on_kill_switch() -> None:
    safety = SafetySnapshot(
        kill_switch=True,
        marketdata_fresh=True,
        marketdata_last_ts=datetime.now(timezone.utc).isoformat(),
        agent_mode="EXECUTE",
    )
    proposal = {
        "proposal_id": "p-ks",
        "valid_until_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "requires_human_approval": False,
        "order": {"symbol": "SPY", "side": "buy", "qty": 1},
    }
    d = decide_execution(proposal=proposal, safety=safety, agent_name="execution-agent", agent_role="execution")
    assert d.decision == "REJECT"
    assert "kill_switch_enabled" in d.reject_reason_codes


def test_decision_rejects_on_stale_marketdata() -> None:
    safety = SafetySnapshot(
        kill_switch=False,
        marketdata_fresh=False,
        marketdata_last_ts=None,
        agent_mode="EXECUTE",
    )
    proposal = {
        "proposal_id": "p-md",
        "valid_until_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "requires_human_approval": False,
        "order": {"symbol": "SPY", "side": "buy", "qty": 1},
    }
    d = decide_execution(proposal=proposal, safety=safety, agent_name="execution-agent", agent_role="execution")
    assert d.decision == "REJECT"
    assert "marketdata_stale_or_missing" in d.reject_reason_codes


def test_decision_rejects_when_requires_human_approval_true() -> None:
    safety = SafetySnapshot(
        kill_switch=False,
        marketdata_fresh=True,
        marketdata_last_ts=datetime.now(timezone.utc).isoformat(),
        agent_mode="EXECUTE",
    )
    proposal = {
        "proposal_id": "p-rha",
        "valid_until_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "requires_human_approval": True,
        "order": {"symbol": "SPY", "side": "buy", "qty": 1},
    }
    d = decide_execution(proposal=proposal, safety=safety, agent_name="execution-agent", agent_role="execution")
    assert d.decision == "REJECT"
    assert "requires_human_approval" in d.reject_reason_codes


def test_decision_rejects_when_valid_until_expired() -> None:
    safety = SafetySnapshot(
        kill_switch=False,
        marketdata_fresh=True,
        marketdata_last_ts=datetime.now(timezone.utc).isoformat(),
        agent_mode="EXECUTE",
    )
    proposal = {
        "proposal_id": "p-exp",
        "valid_until_utc": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "requires_human_approval": False,
        "order": {"symbol": "SPY", "side": "buy", "qty": 1},
    }
    d = decide_execution(proposal=proposal, safety=safety, agent_name="execution-agent", agent_role="execution")
    assert d.decision == "REJECT"
    assert "proposal_expired" in d.reject_reason_codes


def test_decision_ndjson_has_required_keys(tmp_path) -> None:
    # Import here to avoid polluting import graph.
    from backend.execution_agent.main import append_decision_ndjson

    safety = SafetySnapshot(
        kill_switch=True,
        marketdata_fresh=False,
        marketdata_last_ts=None,
        agent_mode="EXECUTE",
    )
    proposal = {
        "proposal_id": "p-out",
        "valid_until_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "requires_human_approval": True,
        "order": {"symbol": "SPY", "side": "buy", "qty": 1},
    }
    d = decide_execution(proposal=proposal, safety=safety, agent_name="execution-agent", agent_role="execution")

    out = tmp_path / "decisions.ndjson"
    ok = append_decision_ndjson(decisions_path=out, decision_obj=d.to_dict())
    assert ok is True

    line = out.read_text(encoding="utf-8").strip().splitlines()[0]
    obj = json.loads(line)

    for k in [
        "decision_id",
        "proposal_id",
        "decided_at_utc",
        "agent_name",
        "agent_role",
        "correlation_id",
        "decision",
        "reject_reason_codes",
        "notes",
        "recommended_order",
        "safety_snapshot",
    ]:
        assert k in obj

