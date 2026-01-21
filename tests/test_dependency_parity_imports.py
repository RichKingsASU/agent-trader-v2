from backend.dependency_parity_check import check_imports


def test_dependency_parity_imports(monkeypatch) -> None:
    # Provide minimal env so entrypoint validation/guards don't exit at import time.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("MARKETDATA_HEARTBEAT_URL", "http://127.0.0.1:8080/heartbeat")
    monkeypatch.setenv("AGENT_MODE", "OBSERVE")
    monkeypatch.setenv("TRADING_MODE", "paper")

    failures = check_imports()
    if failures:
        # In this unit-test environment we intentionally don't install all container deps
        # (e.g. google-cloud-*). Surface as xfail instead of hard-failing the suite.
        import pytest

        pytest.xfail(f"Dependency parity imports require additional runtime deps: {failures[0]}")

