import pytest
from unittest.mock import patch

from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.execution_confirm import ExecutionConfirmTokenError, require_confirm_token_for_live_execution
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.execution.engine import AlpacaBroker, ExecutionEngine, OrderIntent
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

class _DummyResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"dummy http error status={self.status_code}")

    def json(self) -> dict:
        return dict(self._payload)


def test_alpaca_broker_place_order_paper_mode_allowed(monkeypatch, mock_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")

    # Ensure deterministic, no-network behavior in CI: if we accidentally hit the wire, fail.
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    dummy = _DummyResponse(payload={"id": "mock_order_id", "status": "new"})
    with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not run")):
        with patch("backend.execution.engine.requests.post", return_value=dummy) as post:
            out = broker.place_order(intent=sample_intent)
            assert out["id"] == "mock_order_id"
            assert out["status"] == "new"
            assert post.call_count == 1

def test_alpaca_broker_place_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    # Safety invariant: fatal must happen before any broker/network side effects.
    with patch("backend.execution.engine.requests.post", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)

def test_alpaca_broker_place_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env, sample_intent):
    # Blocked by default unless explicitly paper-trading allowed.
    monkeypatch.delenv("TRADING_MODE", raising=False)
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.post", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)

# Similar tests for cancel_order and get_order_status
def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    dummy = _DummyResponse(status_code=204)
    with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not run")):
        with patch("backend.execution.engine.requests.delete", return_value=dummy) as delete:
            out = broker.cancel_order(broker_order_id="test_id")
            assert out["id"] == "test_id"
            assert out["status"] == "canceled"
            assert delete.call_count == 1

def test_alpaca_broker_cancel_order_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.delete", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")

def test_alpaca_broker_cancel_order_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.delete", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.cancel_order(broker_order_id="test_id")


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch, mock_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    dummy = _DummyResponse(payload={"id": "test_id", "status": "new"})
    with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not run")):
        with patch("backend.execution.engine.requests.get", return_value=dummy) as get:
            out = broker.get_order_status(broker_order_id="test_id")
            assert out["id"] == "test_id"
            assert out["status"] == "new"
            assert get.call_count == 1

def test_alpaca_broker_get_order_status_live_url_blocked_in_paper_mode(monkeypatch, mock_live_alpaca_env):
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_live_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.get", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")

def test_alpaca_broker_get_order_status_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_alpaca_env):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    with patch("backend.execution.engine.load_alpaca_env", return_value=mock_alpaca_env):
        broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.get", side_effect=AssertionError("network must not be touched")):
        with pytest.raises(FatalExecutionPathError):
            broker.get_order_status(broker_order_id="test_id")


# --- Tests for ExecutionEngine methods ---

def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not run")):
        out = mock_execution_engine.cancel(broker_order_id="test_id")
        assert out["status"] in ("dry_run", "dry_run_canceled", "canceled", "new")

def test_execution_engine_cancel_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.cancel(broker_order_id="test_id")

def test_execution_engine_cancel_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not run")):
        out = mock_execution_engine.sync_and_ledger_if_filled(broker_order_id="test_id")
        assert out["status"] in ("dry_run", "new")


def test_execution_engine_sync_and_ledger_if_filled_live_url_blocked_in_paper_mode(monkeypatch, mock_execution_engine_live_url):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        mock_execution_engine_live_url.sync_and_ledger_if_filled(broker_order_id="test_id")

def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked_even_if_url_is_paper(monkeypatch, mock_execution_engine):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.delenv("TRADING_MODE", raising=False)
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


# --- Startup hard locks (agent_mode_guard) ---


def test_startup_guard_refuses_missing_trading_mode(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    with pytest.raises(SystemExit) as e:
        enforce_agent_mode_guard()
    assert e.value.code == 13


def test_startup_guard_refuses_non_paper_trading_mode(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(SystemExit) as e:
        enforce_agent_mode_guard()
    assert e.value.code == 13


# --- Confirmation token gate (live paths, fail-closed contract) ---


def test_confirm_token_gate_fails_closed_if_expected_missing(monkeypatch):
    monkeypatch.delenv("EXECUTION_CONFIRM_TOKEN", raising=False)
    with pytest.raises(ExecutionConfirmTokenError, match="missing/empty"):
        require_confirm_token_for_live_execution(provided_token="anything")


def test_confirm_token_gate_requires_provided_token(monkeypatch):
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")
    with pytest.raises(ExecutionConfirmTokenError, match="missing confirmation token"):
        require_confirm_token_for_live_execution(provided_token=None)


def test_confirm_token_gate_refuses_mismatch(monkeypatch):
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")
    with pytest.raises(ExecutionConfirmTokenError, match="mismatch"):
        require_confirm_token_for_live_execution(provided_token="wrong")


def test_confirm_token_gate_allows_exact_match(monkeypatch):
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "expected")
    require_confirm_token_for_live_execution(provided_token="expected")
