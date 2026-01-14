import os
import pytest
from unittest.mock import patch, MagicMock

from backend.execution.engine import ExecutionEngine, OrderIntent, AlpacaBroker
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from functions.utils.apca_env import assert_valid_alpaca_base_url, ApcaEnv
from backend.common.agent_mode import AgentMode


class MockAlpacaBroker:
    def __init__(self, alpaca_env: ApcaEnv):
        self._alpaca = alpaca_env
        self.place_order_called = False
        self.place_order_calls = 0
        self.cancel_order_called = False
        self.get_order_status_called = False

    def place_order(self, *, intent: OrderIntent):
        self.place_order_called = True
        self.place_order_calls += 1
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
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env  # Inject mock env
    
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.place_order(intent=sample_intent)
        mock_fatal.assert_not_called()
        # Assert that the underlying HTTP call would have been made (mocked away in real test)
        # For this test, we just confirm fatal_if_execution_reached was not called.

def test_alpaca_broker_place_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env # Inject mock live env
    
    with pytest.raises(FatalExecutionPathError):
        broker.place_order(intent=sample_intent)

def test_alpaca_broker_place_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "live") # Not paper
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env # Inject mock paper env
    
    with pytest.raises(FatalExecutionPathError):
        broker.place_order(intent=sample_intent)

# Similar tests for cancel_order and get_order_status
def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.cancel_order(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_alpaca_broker_cancel_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.cancel_order(broker_order_id="test_id")

def test_alpaca_broker_cancel_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.cancel_order(broker_order_id="test_id")


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        broker.get_order_status(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_alpaca_broker_get_order_status_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.get_order_status(broker_order_id="test_id")

def test_alpaca_broker_get_order_status_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_alpaca_env
    with pytest.raises(FatalExecutionPathError):
        broker.get_order_status(broker_order_id="test_id")


# --- Tests for ExecutionEngine methods ---

def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.cancel(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_execution_engine_cancel_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")
        mock_fatal.assert_not_called()


def test_execution_engine_sync_and_ledger_if_filled_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.sync_and_ledger_if_filled(broker_order_id="test_id")

def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca.api_base_url = "https://paper-api.alpaca.markets"
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")


# --- Tests for functions/utils/apca_env.py ---

def test_assert_paper_alpaca_base_url_with_paper_url_succeeds():
    paper_url = "https://paper-api.alpaca.markets/v2"
    assert assert_valid_alpaca_base_url(paper_url, AgentMode.PAPER, "paper") == "https://paper-api.alpaca.markets/v2"
    paper_url_no_v2 = "https://paper-api.alpaca.markets"
    assert assert_valid_alpaca_base_url(paper_url_no_v2, AgentMode.PAPER, "paper") == "https://paper-api.alpaca.markets"

def test_assert_paper_alpaca_base_url_with_live_url_fails():
    live_url = "https://api.alpaca.markets/v2"
    with pytest.raises(RuntimeError, match="REFUSED: live Alpaca trading host is forbidden"):
        assert_valid_alpaca_base_url(live_url, AgentMode.PAPER, "paper")

def test_assert_paper_alpaca_base_url_with_non_alpaca_url_fails():
    non_alpaca_url = "https://some-other-api.com"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL validation failed for mode 'PAPER' and trading_mode 'paper'. Got: 'https://some-other-api.com'"):
        assert_valid_alpaca_base_url(non_alpaca_url, AgentMode.PAPER, "paper")

def test_assert_paper_alpaca_base_url_with_http_scheme_fails():
    http_url = "http://paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must be https"):
        assert_valid_alpaca_base_url(http_url, AgentMode.PAPER, "paper")

def test_assert_paper_alpaca_base_url_with_credentials_fails():
    url_with_creds = "https://user:pass@paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include credentials"):
        assert_valid_alpaca_base_url(url_with_creds, AgentMode.PAPER, "paper")

def test_assert_paper_alpaca_base_url_with_port_fails():
    url_with_port = "https://paper-api.alpaca.markets:8080"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not specify a port"):
        assert_valid_alpaca_base_url(url_with_port, AgentMode.PAPER, "paper")

def test_assert_paper_alpaca_base_url_with_query_fails():
    url_with_query = "https://paper-api.alpaca.markets?query=param"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include query/fragment"):
        assert_valid_alpaca_base_url(url_with_query, AgentMode.PAPER, "paper")


def test_paper_execution_symbol_cooldown_blocks_rapid_retrade(monkeypatch, mock_execution_engine, sample_intent):
    """
    Cooldown guard should prevent overtrading in paper mode.
    """
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXEC_SYMBOL_COOLDOWN_S", "600")  # 10 minutes

    # Avoid external dependencies in unit test: stub pre-trade assertions + risk manager.
    mock_execution_engine._assert_pre_trade = lambda *args, **kwargs: None  # type: ignore[method-assign]
    mock_execution_engine._risk.validate = lambda *args, **kwargs: type(  # type: ignore[method-assign]
        "R", (), {"allowed": True, "reason": "ok", "checks": []}
    )()

    r1 = mock_execution_engine.execute_intent(intent=sample_intent)
    assert r1.status == "placed"
    assert mock_execution_engine._broker.place_order_calls == 1

    r2 = mock_execution_engine.execute_intent(intent=sample_intent)
    assert r2.status == "rejected"
    assert r2.risk.allowed is False
    assert r2.risk.reason == "symbol_cooldown"
    assert mock_execution_engine._broker.place_order_calls == 1  # second placement blocked
