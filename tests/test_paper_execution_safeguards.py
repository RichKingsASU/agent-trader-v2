import os
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import replace

from backend.execution.engine import ExecutionEngine, OrderIntent, AlpacaBroker
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.streams.alpaca_env import AlpacaEnv
from functions.utils.apca_env import assert_paper_alpaca_base_url


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
    # Default to paper settings for tests (matches backend.execution.engine expectations)
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

def _mock_http_response(*, json_payload: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_payload
    r.raise_for_status.return_value = None
    return r


def test_alpaca_broker_place_order_paper_mode_allowed(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    # Ensure base URL is derived from injected env
    broker._base = broker._alpaca.trading_base_v2
    
    with patch("backend.execution.engine.fatal_if_execution_reached") as mock_fatal, patch(
        "backend.execution.engine.requests.post"
    ) as mock_post:
        mock_post.return_value = _mock_http_response(
            json_payload={"id": "mock_order_id", "status": "new"}
        )
        resp = broker.place_order(intent=sample_intent)
        mock_fatal.assert_not_called()
        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        assert "paper-api.alpaca.markets" in url
        assert resp["id"] == "mock_order_id"
        assert resp["status"] == "new"

def test_alpaca_broker_place_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    # Construct broker with paper env (satisfies init) then inject a non-paper trading host
    paper_env = replace(mock_live_alpaca_env, trading_host="https://paper-api.alpaca.markets")
    with patch("backend.execution.engine.load_alpaca_env", return_value=paper_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    broker._base = broker._alpaca.trading_base_v2
    
    with patch("backend.execution.engine.requests.post") as mock_post:
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)
        mock_post.assert_not_called()

def test_alpaca_broker_place_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "live") # Not paper
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._base = broker._alpaca.trading_base_v2
    
    with patch("backend.execution.engine.requests.post") as mock_post:
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)
        mock_post.assert_not_called()

# Similar tests for cancel_order and get_order_status
def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.fatal_if_execution_reached") as mock_fatal, patch(
        "backend.execution.engine.requests.delete"
    ) as mock_delete:
        mock_delete.return_value = _mock_http_response(json_payload={}, status_code=204)
        resp = broker.cancel_order(broker_order_id="test_id")
        mock_fatal.assert_not_called()
        mock_delete.assert_called_once()
        url = mock_delete.call_args.args[0]
        assert "paper-api.alpaca.markets" in url
        assert resp["id"] == "test_id"
        assert resp["status"] == "canceled"

def test_alpaca_broker_cancel_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    paper_env = replace(mock_live_alpaca_env, trading_host="https://paper-api.alpaca.markets")
    with patch("backend.execution.engine.load_alpaca_env", return_value=paper_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.requests.delete") as mock_delete:
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")
        mock_delete.assert_not_called()

def test_alpaca_broker_cancel_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.requests.delete") as mock_delete:
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")
        mock_delete.assert_not_called()


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.fatal_if_execution_reached") as mock_fatal, patch(
        "backend.execution.engine.requests.get"
    ) as mock_get:
        mock_get.return_value = _mock_http_response(
            json_payload={"id": "test_id", "status": "new"}
        )
        resp = broker.get_order_status(broker_order_id="test_id")
        mock_fatal.assert_not_called()
        mock_get.assert_called_once()
        url = mock_get.call_args.args[0]
        assert "paper-api.alpaca.markets" in url
        assert resp["id"] == "test_id"

def test_alpaca_broker_get_order_status_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    paper_env = replace(mock_live_alpaca_env, trading_host="https://paper-api.alpaca.markets")
    with patch("backend.execution.engine.load_alpaca_env", return_value=paper_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = mock_live_alpaca_env
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.requests.get") as mock_get:
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")
        mock_get.assert_not_called()

def test_alpaca_broker_get_order_status_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "live")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.requests.get") as mock_get:
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")
        mock_get.assert_not_called()


@pytest.mark.parametrize(
    "bad_trading_host",
    [
        "https://api.alpaca.markets",
        "https://example.com",
    ],
)
def test_alpaca_broker_any_other_api_host_fails_in_paper_mode(monkeypatch, mock_alpaca_env, sample_intent, bad_trading_host):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)
    broker._alpaca = replace(mock_alpaca_env, trading_host=bad_trading_host)
    broker._base = broker._alpaca.trading_base_v2
    with patch("backend.execution.engine.requests.post") as mock_post:
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)
        mock_post.assert_not_called()


# --- Tests for ExecutionEngine methods ---

def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = replace(
        mock_execution_engine._broker._alpaca, trading_host="https://paper-api.alpaca.markets"
    )
    with patch("backend.execution.engine.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.cancel(broker_order_id="test_id")
        mock_fatal.assert_not_called()

def test_execution_engine_cancel_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = replace(
        mock_execution_engine._broker._alpaca, trading_host="https://paper-api.alpaca.markets"
    )
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = replace(
        mock_execution_engine._broker._alpaca, trading_host="https://paper-api.alpaca.markets"
    )
    with patch("backend.execution.engine.fatal_if_execution_reached") as mock_fatal:
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")
        mock_fatal.assert_not_called()


def test_execution_engine_sync_and_ledger_if_filled_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.sync_and_ledger_if_filled(broker_order_id="test_id")

def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    # Simulate internal broker instance being paper-configured
    mock_execution_engine._broker._alpaca = replace(
        mock_execution_engine._broker._alpaca, trading_host="https://paper-api.alpaca.markets"
    )
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")


# --- Tests for functions/utils/apca_env.py ---

def test_assert_paper_alpaca_base_url_with_paper_url_succeeds():
    paper_url = "https://paper-api.alpaca.markets/v2"
    assert assert_paper_alpaca_base_url(paper_url) == "https://paper-api.alpaca.markets/v2"
    paper_url_no_v2 = "https://paper-api.alpaca.markets"
    assert assert_paper_alpaca_base_url(paper_url_no_v2) == "https://paper-api.alpaca.markets"

def test_assert_paper_alpaca_base_url_with_live_url_fails():
    live_url = "https://api.alpaca.markets/v2"
    with pytest.raises(RuntimeError, match="REFUSED: live Alpaca trading host is forbidden"):
        assert_paper_alpaca_base_url(live_url)

def test_assert_paper_alpaca_base_url_with_non_alpaca_url_fails():
    non_alpaca_url = "https://some-other-api.com"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must be paper host"):
        assert_paper_alpaca_base_url(non_alpaca_url)

def test_assert_paper_alpaca_base_url_with_http_scheme_fails():
    http_url = "http://paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must be https"):
        assert_paper_alpaca_base_url(http_url)

def test_assert_paper_alpaca_base_url_with_credentials_fails():
    url_with_creds = "https://user:pass@paper-api.alpaca.markets"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include credentials"):
        assert_paper_alpaca_base_url(url_with_creds)

def test_assert_paper_alpaca_base_url_with_port_fails():
    url_with_port = "https://paper-api.alpaca.markets:8080"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not specify a port"):
        assert_paper_alpaca_base_url(url_with_port)

def test_assert_paper_alpaca_base_url_with_query_fails():
    url_with_query = "https://paper-api.alpaca.markets?query=param"
    with pytest.raises(RuntimeError, match="REFUSED: Alpaca base URL must not include query/fragment"):
        assert_paper_alpaca_base_url(url_with_query)
