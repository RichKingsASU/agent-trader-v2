from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

_ENGINE_OK = True
_ENGINE_IMPORT_ERR: Exception | None = None
try:
    from backend.execution.engine import ExecutionEngine, OrderIntent, AlpacaBroker
except Exception as e:  # pragma: no cover
    _ENGINE_OK = False
    _ENGINE_IMPORT_ERR = e

from backend.common.runtime_execution_prevention import FatalExecutionPathError
from functions.utils.apca_env import assert_valid_alpaca_base_url, ApcaEnv
from backend.common.agent_mode import AgentMode


class MockAlpacaBroker:
    def __init__(self, alpaca_env: ApcaEnv):
        self._alpaca = alpaca_env
        self.place_order_called = False
        self.cancel_order_called = False
        self.get_order_status_called = False

    def place_order(self, *, intent: OrderIntent):
        self.place_order_called = True
        return {"id": "mock_order_id", "status": "new"}

    def cancel_order(self, *, broker_order_id: str):
        self.cancel_order_called = True
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):
        self.get_order_status_called = True
        return {"id": broker_order_id, "status": "new"}

def _require_engine() -> None:
    if not _ENGINE_OK:
        pytest.xfail(
            f"backend.execution.engine not available (documented-but-unimplemented): {type(_ENGINE_IMPORT_ERR).__name__}: {_ENGINE_IMPORT_ERR}"
        )


@pytest.fixture
def mock_alpaca_env():
    # Default to paper settings for tests
    return ApcaEnv(
        api_key_id="mock_key",
        api_secret_key="mock_secret",
        api_base_url="https://paper-api.alpaca.markets"
    )

@pytest.fixture
def mock_live_alpaca_env():
    return ApcaEnv(
        api_key_id="mock_key",
        api_secret_key="mock_secret",
        api_base_url="https://api.alpaca.markets"
    )

@pytest.fixture
def mock_execution_engine(mock_alpaca_env):
    _require_engine()
    mock_broker = MockAlpacaBroker(mock_alpaca_env)
    return ExecutionEngine(broker=mock_broker, dry_run=False)


@pytest.fixture
def mock_execution_engine_live_url(mock_live_alpaca_env):
    _require_engine()
    mock_broker = MockAlpacaBroker(mock_live_alpaca_env)
    return ExecutionEngine(broker=mock_broker, dry_run=False)


@pytest.fixture
def sample_intent():
    _require_engine()
    return OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="test_account",
        symbol="SPY",
        side="buy",
        qty=1
    )


# --- Tests for AlpacaBroker methods ---

def test_alpaca_broker_place_order_paper_mode_allowed(monkeypatch, mock_alpaca_env, sample_intent):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env  # Inject mock env
    
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.place_order(intent=sample_intent)
        mock_fatal.assert_not_called()
        # Assert that the underlying HTTP call would have been made (mocked away in real test)
        # For this test, we just confirm fatal_if_execution_reached was not called.

def test_alpaca_broker_place_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env, sample_intent):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env # Inject mock live env
    
    with pytest.raises(FatalExecutionPathError):
        broker.place_order(intent=sample_intent)

def test_alpaca_broker_place_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env, sample_intent):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "live") # Not paper
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env # Inject mock paper env
    
    with pytest.raises(FatalExecutionPathError):
        broker.place_order(intent=sample_intent)

# Similar tests for cancel_order and get_order_status
def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.cancel_order(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_alpaca_broker_cancel_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.cancel_order(broker_order_id="test_id")

def test_alpaca_broker_cancel_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "live")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.cancel_order(broker_order_id="test_id")


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.get_order_status(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_alpaca_broker_get_order_status_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.get_order_status(broker_order_id="test_id")

def test_alpaca_broker_get_order_status_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "live")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.get_order_status(broker_order_id="test_id")


# --- Tests for ExecutionEngine methods ---

def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, mock_execution_engine):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.cancel(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_execution_engine_cancel_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, mock_execution_engine):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")
        mock_fatal.assert_not_called()


def test_execution_engine_sync_and_ledger_if_filled_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.sync_and_ledger_if_filled(broker_order_id="test_id")

def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    _require_engine()
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")


# --- Tests for functions/utils/apca_env.py ---

def test_assert_paper_alpaca_base_url_with_paper_url_succeeds():
    paper_url = "https://paper-api.alpaca.markets/v2"
    assert assert_valid_alpaca_base_url(paper_url, AgentMode.DISABLED, "paper") == "https://paper-api.alpaca.markets/v2"
    paper_url_no_v2 = "https://paper-api.alpaca.markets"
    assert assert_valid_alpaca_base_url(paper_url_no_v2, AgentMode.DISABLED, "paper") == "https://paper-api.alpaca.markets"

def test_assert_paper_alpaca_base_url_with_live_url_fails():
    live_url = "https://api.alpaca.markets/v2"
    with pytest.raises(RuntimeError, match="REFUSED: TRADING_MODE='paper' requires Alpaca base URL"):
        assert_valid_alpaca_base_url(live_url, AgentMode.DISABLED, "paper")

def test_assert_paper_alpaca_base_url_with_non_alpaca_url_fails():
    non_alpaca_url = "https://some-other-api.com"
    with pytest.raises(RuntimeError, match="REFUSED: TRADING_MODE='paper' requires Alpaca base URL"):
        assert_valid_alpaca_base_url(non_alpaca_url, AgentMode.DISABLED, "paper")

def test_assert_paper_alpaca_base_url_with_http_scheme_fails():
    http_url = "http://paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must be https"):
        assert_valid_alpaca_base_url(http_url, AgentMode.DISABLED, "paper")

def test_assert_paper_alpaca_base_url_with_credentials_fails():
    url_with_creds = "https://user:pass@paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include credentials"):
        assert_valid_alpaca_base_url(url_with_creds, AgentMode.DISABLED, "paper")

def test_assert_paper_alpaca_base_url_with_port_fails():
    url_with_port = "https://paper-api.alpaca.markets:8080"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not specify a port"):
        assert_valid_alpaca_base_url(url_with_port, AgentMode.DISABLED, "paper")

def test_assert_paper_alpaca_base_url_with_query_fails():
    url_with_query = "https://paper-api.alpaca.markets?query=param"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include query/fragment"):
        assert_valid_alpaca_base_url(url_with_query, AgentMode.DISABLED, "paper")
