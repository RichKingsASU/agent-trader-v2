import json


def _set_identity_env(monkeypatch):
    monkeypatch.setenv("REPO_ID", "agent-trader-v2")
    monkeypatch.setenv("AGENT_NAME", "unit-test-agent")
    monkeypatch.setenv("AGENT_ROLE", "ops")
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("GIT_SHA", "deadbeef")


def test_intent_log_has_required_keys(monkeypatch, capsys):
    _set_identity_env(monkeypatch)

    from backend.observability.logger import intent_start, intent_end

    ctx = intent_start("test_intent", "Testing intent schema.", payload={"api_key": "SHOULD_NOT_LEAK"})
    intent_end(ctx, "success")

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) >= 2
    start = json.loads(out[-2])
    end = json.loads(out[-1])

    required = {
        "timestamp",
        "level",
        "repo_id",
        "agent_name",
        "agent_role",
        "agent_mode",
        "git_sha",
        "intent_id",
        "correlation_id",
        "trace_id",
        "intent_type",
        "intent_summary",
        "intent_payload",
        "outcome",
    }
    for key in required:
        assert key in start
        assert key in end

    assert start["outcome"] == "started"
    assert end["outcome"] == "success"
    assert isinstance(end.get("duration_ms"), int)
    # Redaction
    assert start["intent_payload"]["api_key"] != "SHOULD_NOT_LEAK"

