import os
import pytest
from unittest.mock import patch, MagicMock

from backend.execution.engine import ExecutionEngine, OrderIntent, AlpacaBroker
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.streams.alpaca_env import AlpacaEnv
from functions.utils.apca_env import assert_valid_alpaca_base_url
from backend.common.agent_mode import AgentMode, AgentModeError


class MockAlpacaBroker:
    def __init__(self, alpaca_env: AlpacaEnv):
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


@pytest.fixture
def mock_alpaca_env():
    # Default to paper settings for tests
    return AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://paper-api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )

@pytest.fixture
def mock_live_alpaca_env():
    return AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )

@pytest.fixture
def mock_execution_engine(mock_alpaca_env):
    mock_broker = MockAlpacaBroker(mock_alpaca_env)
    return ExecutionEngine(broker=mock_broker, dry_run=False)


@pytest.fixture
def mock_execution_engine_live_url(mock_live_alpaca_env):
    mock_broker = MockAlpacaBroker(mock_live_alpaca_env)
    return ExecutionEngine(broker=mock_broker, dry_run=False)


@pytest.fixture
def sample_intent():
    return OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="test_account",
        symbol="SPY",
        side="buy",
        qty=1
    )


# --- Tests for AlpacaBroker methods ---

def test_alpaca_broker_place_order_paper_mode_allowed(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with (
        patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env),
        patch("backend.execution.engine.requests.post") as mock_post,
        patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal,
    ):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"id": "mock_order_id", "status": "new"}
        mock_post.return_value = fake_resp

        broker = AlpacaBroker(request_timeout_s=10.0)
        broker.place_order(intent=sample_intent)

        mock_fatal.assert_not_called()
        mock_post.assert_called_once()

def test_alpaca_broker_place_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)

def test_alpaca_broker_place_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "live") # Not paper
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)

# Similar tests for cancel_order and get_order_status
def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with (
        patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env),
        patch("backend.execution.engine.requests.delete") as mock_delete,
        patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal,
    ):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"id": "test_id", "status": "canceled"}
        mock_delete.return_value = fake_resp

        broker = AlpacaBroker(request_timeout_s=10.0)
        broker.cancel_order(broker_order_id="test_id")

        mock_fatal.assert_not_called()
        mock_delete.assert_called_once()

def test_alpaca_broker_cancel_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")

def test_alpaca_broker_cancel_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with (
        patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env),
        patch("backend.execution.engine.requests.get") as mock_get,
        patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal,
    ):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"id": "test_id", "status": "new"}
        mock_get.return_value = fake_resp

        broker = AlpacaBroker(request_timeout_s=10.0)
        broker.get_order_status(broker_order_id="test_id")

        mock_fatal.assert_not_called()
        mock_get.assert_called_once()

def test_alpaca_broker_get_order_status_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")

def test_alpaca_broker_get_order_status_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")


# --- Tests for ExecutionEngine methods ---

def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://paper-api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )
    # Cancel is a broker-side action and remains guarded by AGENT_MODE=LIVE.
    with pytest.raises(AgentModeError):
        mock_execution_engine.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("TRADING_MODE", "paper")
    # AGENT_MODE guard triggers before paper/live URL checks.
    with pytest.raises(AgentModeError):
        mock_execution_engine_live_url.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://paper-api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )
    with pytest.raises(AgentModeError):
        mock_execution_engine.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://paper-api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")
        mock_fatal.assert_not_called()


def test_execution_engine_sync_and_ledger_if_filled_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.sync_and_ledger_if_filled(broker_order_id="test_id")

def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = AlpacaEnv(
        key_id="mock_key",
        secret_key="mock_secret",
        trading_host="https://paper-api.alpaca.markets",
        data_host="https://data.alpaca.markets",
    )
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")


# --- Tests for functions/utils/apca_env.py ---

def test_assert_paper_alpaca_base_url_with_paper_url_succeeds():
    paper_url = "https://paper-api.alpaca.markets/v2"
    assert assert_valid_alpaca_base_url(paper_url, AgentMode.WARMUP, "paper") == "https://paper-api.alpaca.markets/v2"
    paper_url_no_v2 = "https://paper-api.alpaca.markets"
    assert assert_valid_alpaca_base_url(paper_url_no_v2, AgentMode.WARMUP, "paper") == "https://paper-api.alpaca.markets"

def test_assert_paper_alpaca_base_url_with_live_url_fails():
    live_url = "https://api.alpaca.markets/v2"
    with pytest.raises(RuntimeError, match="TRADING_MODE='paper' requires Alpaca base URL"):
        assert_valid_alpaca_base_url(live_url, AgentMode.WARMUP, "paper")

def test_assert_paper_alpaca_base_url_with_non_alpaca_url_fails():
    non_alpaca_url = "https://some-other-api.com"
    with pytest.raises(RuntimeError, match="TRADING_MODE='paper' requires Alpaca base URL"):
        assert_valid_alpaca_base_url(non_alpaca_url, AgentMode.WARMUP, "paper")

def test_assert_paper_alpaca_base_url_with_http_scheme_fails():
    http_url = "http://paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must be https"):
        assert_valid_alpaca_base_url(http_url, AgentMode.WARMUP, "paper")

def test_assert_paper_alpaca_base_url_with_credentials_fails():
    url_with_creds = "https://user:pass@paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include credentials"):
        assert_valid_alpaca_base_url(url_with_creds, AgentMode.WARMUP, "paper")

def test_assert_paper_alpaca_base_url_with_port_fails():
    url_with_port = "https://paper-api.alpaca.markets:8080"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not specify a port"):
        assert_valid_alpaca_base_url(url_with_port, AgentMode.WARMUP, "paper")

def test_assert_paper_alpaca_base_url_with_query_fails():
    url_with_query = "https://paper-api.alpaca.markets?query=param"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include query/fragment"):
        assert_valid_alpaca_base_url(url_with_query, AgentMode.WARMUP, "paper")
