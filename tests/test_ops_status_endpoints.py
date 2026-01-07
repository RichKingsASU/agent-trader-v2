import asyncio
import importlib
import sys


def _import_fresh(module_name: str):
    # Ensure import-time env contracts are evaluated with test-provided env.
    for k in list(sys.modules.keys()):
        if k == module_name or k.startswith(module_name + "."):
            sys.modules.pop(k, None)
    return importlib.import_module(module_name)


def _get_route_endpoint(app, path: str):
    for r in getattr(app, "routes", []):
        if getattr(r, "path", None) == path:
            return getattr(r, "endpoint", None)
    raise AssertionError(f"Route not found: {path}")


def _assert_minimal_contract(payload: dict):
    assert isinstance(payload, dict)
    for k in ("uptime", "last_heartbeat", "data_freshness_seconds", "build_sha", "agent_mode"):
        assert k in payload

    assert isinstance(payload["uptime"], (int, float))
    assert payload["uptime"] >= 0

    assert payload["last_heartbeat"] is None or isinstance(payload["last_heartbeat"], str)

    assert payload["data_freshness_seconds"] is None or isinstance(payload["data_freshness_seconds"], (int, float))
    if payload["data_freshness_seconds"] is not None:
        assert payload["data_freshness_seconds"] >= 0

    assert isinstance(payload["build_sha"], str)
    assert payload["build_sha"] != ""

    assert isinstance(payload["agent_mode"], str)
    assert payload["agent_mode"] != ""


def test_marketdata_mcp_server_ops_status(monkeypatch):
    # Satisfy import-time streamer env contract.
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("AGENT_MODE", "OBSERVE")
    monkeypatch.setenv("GIT_SHA", "deadbeef")

    mod = _import_fresh("backend.app")
    endpoint = _get_route_endpoint(mod.app, "/ops/status")
    payload = asyncio.run(endpoint())
    _assert_minimal_contract(payload)


def test_strategy_engine_ops_status(monkeypatch):
    # Satisfy import-time config contract + agent mode guard.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("MARKETDATA_HEARTBEAT_URL", "http://127.0.0.1:8080/heartbeat")
    monkeypatch.setenv("AGENT_MODE", "OBSERVE")
    monkeypatch.setenv("GIT_SHA", "deadbeef")

    mod = _import_fresh("backend.strategy_engine.service")
    endpoint = _get_route_endpoint(mod.app, "/ops/status")
    payload = asyncio.run(endpoint())
    _assert_minimal_contract(payload)

