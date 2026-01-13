from __future__ import annotations

import json

import pytest


def _json_lines(stdout: str) -> list[dict]:
    out: list[dict] = []
    for line in (stdout or "").splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def test_live_execution_attempt_emits_audit_event_with_required_fields(monkeypatch, capsys) -> None:
    """
    Compliance assertion:
    - LIVE execution attempt MUST log event_type=execution_attempt
    - Must include: AGENT_NAME, AGENT_ROLE, AGENT_VERSION, confirm_token_id, timestamp
    - Must happen before execution proceeds (we abort immediately after to avoid side effects)
    """
    from backend.common.logging import init_structured_logging
    from backend.execution.engine import DryRunBroker, ExecutionEngine, OrderIntent, RiskManager
    import backend.execution.engine as engine_mod

    # Ensure JSON logs are emitted to stdout for parsing.
    init_structured_logging(service="test-execution-engine")

    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("AGENT_NAME", "pytest-agent")
    monkeypatch.setenv("AGENT_ROLE", "execution")
    monkeypatch.setenv("AGENT_VERSION", "v-test-1")

    class StopAfterAudit(Exception):
        pass

    def _stop(_metadata):
        raise StopAfterAudit("stop_after_audit")

    # Abort immediately after the audit event to avoid hitting Firestore/broker side effects.
    monkeypatch.setattr(engine_mod, "resolve_tenant_id_from_metadata", _stop)

    engine = ExecutionEngine(
        broker=DryRunBroker(),
        broker_name="alpaca",
        dry_run=False,  # LIVE attempt (compliance scope)
        risk=RiskManager(),
        enable_smart_routing=False,
        ledger=None,
        reservations=None,
    )

    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
        order_type="market",
        time_in_force="day",
        limit_price=None,
        client_intent_id="intent-1",
        metadata={"confirm_token_id": "ctok_123"},
    )

    with pytest.raises(StopAfterAudit):
        engine.execute_intent(intent=intent)

    stdout = capsys.readouterr().out
    events = _json_lines(stdout)
    attempt = next((e for e in events if e.get("event_type") == "execution_attempt"), None)
    assert attempt is not None, "missing execution_attempt audit event"

    for k in ("AGENT_NAME", "AGENT_ROLE", "AGENT_VERSION", "confirm_token_id", "timestamp"):
        assert k in attempt, f"missing required audit field: {k}"

    assert attempt["AGENT_NAME"] == "pytest-agent"
    assert attempt["AGENT_ROLE"] == "execution"
    assert attempt["AGENT_VERSION"] == "v-test-1"
    assert attempt["confirm_token_id"] == "ctok_123"


def test_live_execution_fails_closed_if_audit_emit_fails(monkeypatch) -> None:
    """
    Compliance assertion:
    - Execution MUST NOT proceed if the audit log cannot be emitted.
    """
    from backend.common.logging import init_structured_logging
    from backend.execution.engine import DryRunBroker, ExecutionEngine, OrderIntent, RiskManager
    import backend.execution.engine as engine_mod
    import backend.common.logging as common_logging

    init_structured_logging(service="test-execution-engine")

    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("AGENT_NAME", "pytest-agent")
    monkeypatch.setenv("AGENT_ROLE", "execution")
    monkeypatch.setenv("AGENT_VERSION", "v-test-1")

    proceeded = {"called": False}

    def _mark_proceeded(_metadata):
        proceeded["called"] = True
        return None

    # If we reach this, we "proceeded" beyond the audit boundary.
    monkeypatch.setattr(engine_mod, "resolve_tenant_id_from_metadata", _mark_proceeded)

    def _fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated_audit_failure")

    monkeypatch.setattr(common_logging, "log_event", _fail_audit)

    engine = ExecutionEngine(
        broker=DryRunBroker(),
        broker_name="alpaca",
        dry_run=False,  # LIVE attempt (compliance scope)
        risk=RiskManager(),
        enable_smart_routing=False,
        ledger=None,
        reservations=None,
    )

    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
        order_type="market",
        time_in_force="day",
        limit_price=None,
        client_intent_id="intent-1",
        metadata={"confirm_token_id": "ctok_123"},
    )

    with pytest.raises(RuntimeError, match="audit_log_failed"):
        engine.execute_intent(intent=intent)

    assert proceeded["called"] is False, "execution proceeded despite audit emit failure"

