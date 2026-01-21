import asyncio


def test_agents_yaml_load_and_polling_with_mocked_http(tmp_path, monkeypatch):
    # mission_control has startup guards at import time.
    monkeypatch.setenv("AGENT_MODE", "OBSERVE")
    monkeypatch.setenv("TRADING_MODE", "paper")

    from backend.mission_control.main import AgentConfig, MissionControlState, load_agents_config

    agents_yaml = tmp_path / "agents.yaml"
    agents_yaml.write_text(
        """
agents:
  - agent_name: a1
    service_dns: http://a1.local
    kind: strategy
    expected_endpoints: [/ops/status, /healthz]
    criticality: important
  - agent_name: a2
    service_dns: http://a2.local
    kind: marketdata
    expected_endpoints: [/ops/status, /healthz, /heartbeat]
    criticality: critical
""".lstrip(),
        encoding="utf-8",
    )

    agents = load_agents_config(str(agents_yaml))
    assert [a.agent_name for a in agents] == ["a1", "a2"]
    assert all(isinstance(a, AgentConfig) for a in agents)

    class _Resp:
        def __init__(self, status_code: int, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("no json")
            return self._payload

    class _Client:
        async def get(self, url, timeout=None, headers=None):  # noqa: ARG002
            # a1 is healthy; a2 healthz times out (unreachable)
            if url == "http://a1.local/healthz":
                return _Resp(200, {"ok": True})
            if url == "http://a1.local/ops/status":
                return _Resp(200, {"service": "a1", "token": "SHOULD_BE_REDACTED"})

            if url == "http://a2.local/healthz":
                raise TimeoutError("timeout")
            if url == "http://a2.local/ops/status":
                raise TimeoutError("timeout")
            if url == "http://a2.local/heartbeat":
                return _Resp(404, {"detail": "not found"})

            raise AssertionError(f"unexpected url: {url}")

    async def _run():
        state = MissionControlState(agents=agents)
        await state.poll_once(client=_Client(), per_agent_timeout_s=0.1)

        snap = await state.get_status_snapshot()
        assert snap["a1"].online is True
        assert snap["a2"].online is False

        # Raw ops/status must be redacted
        raw = snap["a1"].raw_ops_status_redacted or {}
        assert raw.get("token") == "***REDACTED***"

        # Event buffer should record the poll cycle
        events = await state.events.recent(limit=5)
        assert events
        assert events[0]["type"] == "mission_control.poll"
        assert {o["agent_name"] for o in events[0]["outcomes"]} == {"a1", "a2"}

    asyncio.run(_run())

