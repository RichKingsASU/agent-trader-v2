import pytest

from backend.common.execution_confirm import ExecutionConfirmTokenError
from backend.common.live_execution_authorization import (
    LiveExecutionAuthorizationError,
    assert_live_execution_authorized,
)


def test_agent_mode_not_live_fails(monkeypatch):
    # All other conditions satisfied, but AGENT_MODE != LIVE => FAIL
    monkeypatch.setenv("AGENT_MODE", "DISABLED")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")

    with pytest.raises(LiveExecutionAuthorizationError, match=r"AGENT_MODE!=LIVE"):
        assert_live_execution_authorized(provided_confirm_token="expected")


def test_trading_mode_not_live_fails(monkeypatch):
    # All other conditions satisfied, but TRADING_MODE != live => FAIL
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")

    with pytest.raises(LiveExecutionAuthorizationError, match=r"TRADING_MODE!=live"):
        assert_live_execution_authorized(provided_confirm_token="expected")


def test_missing_execution_confirm_token_fails(monkeypatch):
    # Missing EXECUTION_CONFIRM_TOKEN => FAIL (fail-closed)
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.delenv("EXECUTION_CONFIRM_TOKEN", raising=False)

    with pytest.raises(ExecutionConfirmTokenError, match=r"EXECUTION_CONFIRM_TOKEN is missing/empty"):
        assert_live_execution_authorized(provided_confirm_token="any")


def test_invalid_execution_confirm_token_fails(monkeypatch):
    # Invalid EXECUTION_CONFIRM_TOKEN => FAIL
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")

    with pytest.raises(ExecutionConfirmTokenError, match=r"token mismatch"):
        assert_live_execution_authorized(provided_confirm_token="wrong")


def test_live_api_url_plus_paper_mode_fails(monkeypatch):
    # Live API URL + paper mode => FAIL
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")

    # This specific failure is about the URL/mode mismatch (not token).
    with pytest.raises(
        LiveExecutionAuthorizationError,
        match=r"Live Alpaca API URL is forbidden when TRADING_MODE=paper",
    ):
        assert_live_execution_authorized(provided_confirm_token="expected")


def test_all_conditions_satisfied_allows_execution(monkeypatch):
    # All conditions satisfied => execution allowed
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")

    # Must not raise
    assert_live_execution_authorized(provided_confirm_token="expected")
    assert True

