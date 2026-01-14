import pytest
from unittest.mock import patch

from backend.common.env import assert_paper_alpaca_base_url
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.execution.engine import AlpacaBroker, ExecutionEngine, OrderIntent, RiskDecision
from backend.streams.alpaca_env import AlpacaEnv


def _set_apca_env(monkeypatch, *, base_url: str) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "mock_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "mock_secret")
    monkeypatch.setenv("APCA_API_BASE_URL", base_url)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _BrokerStub:
    def __init__(self, *, alpaca_env: AlpacaEnv):
        self._alpaca = alpaca_env
        self.place_order_calls = 0
        self.cancel_calls = 0
        self.status_calls = 0

    def place_order(self, *, intent: OrderIntent):
        self.place_order_calls += 1
        return {"id": f"mock_{self.place_order_calls}", "status": "new"}

    def cancel_order(self, *, broker_order_id: str):
        self.cancel_calls += 1
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):
        self.status_calls += 1
        return {"id": broker_order_id, "status": "new"}


@pytest.fixture
def sample_intent():
    return OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="test_account",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={},
    )


# --- Tests for AlpacaBroker methods (paper execution guardrails) ---


def test_alpaca_broker_place_order_paper_mode_allowed(monkeypatch, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "paper")
    _set_apca_env(monkeypatch, base_url="https://paper-api.alpaca.markets")
    broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.post") as mock_post, patch(
        "backend.common.runtime_execution_prevention.fatal_if_execution_reached"
    ) as mock_fatal:
        mock_post.return_value = _Resp({"id": "mock_order_id", "status": "new"})
        out = broker.place_order(intent=sample_intent)
        assert out["id"] == "mock_order_id"
        mock_fatal.assert_not_called()


def test_alpaca_broker_place_order_non_paper_mode_blocked(monkeypatch, sample_intent):
    monkeypatch.setenv("TRADING_MODE", "live")
    _set_apca_env(monkeypatch, base_url="https://paper-api.alpaca.markets")
    broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.post") as mock_post:
        mock_post.return_value = _Resp({"id": "should_not_be_used", "status": "new"})
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=sample_intent)


def test_alpaca_broker_cancel_order_paper_mode_allowed(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    _set_apca_env(monkeypatch, base_url="https://paper-api.alpaca.markets")
    broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.delete") as mock_delete, patch(
        "backend.common.runtime_execution_prevention.fatal_if_execution_reached"
    ) as mock_fatal:
        mock_delete.return_value = _Resp({"id": "test_id", "status": "canceled"})
        out = broker.cancel_order(broker_order_id="test_id")
        assert out["status"] == "canceled"
        mock_fatal.assert_not_called()


def test_alpaca_broker_get_order_status_paper_mode_allowed(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    _set_apca_env(monkeypatch, base_url="https://paper-api.alpaca.markets")
    broker = AlpacaBroker(request_timeout_s=10.0)

    with patch("backend.execution.engine.requests.get") as mock_get, patch(
        "backend.common.runtime_execution_prevention.fatal_if_execution_reached"
    ) as mock_fatal:
        mock_get.return_value = _Resp({"id": "test_id", "status": "new"})
        out = broker.get_order_status(broker_order_id="test_id")
        assert out["status"] == "new"
        mock_fatal.assert_not_called()


# --- ExecutionEngine paper-override behavior (cancel/status) ---


@pytest.fixture
def engine_with_paper_alpaca_stub():
    broker = _BrokerStub(
        alpaca_env=AlpacaEnv(
            key_id="k",
            secret_key="s",
            trading_host="https://paper-api.alpaca.markets",
            data_host="https://data.alpaca.markets",
        )
    )
    return ExecutionEngine(broker=broker, dry_run=False)


@pytest.fixture
def engine_with_live_host_stub():
    broker = _BrokerStub(
        alpaca_env=AlpacaEnv(
            key_id="k",
            secret_key="s",
            trading_host="https://api.alpaca.markets",
            data_host="https://data.alpaca.markets",
        )
    )
    return ExecutionEngine(broker=broker, dry_run=False)


def test_execution_engine_cancel_paper_mode_allowed(monkeypatch, engine_with_paper_alpaca_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        out = engine_with_paper_alpaca_stub.cancel(broker_order_id="test_id")
        assert out["status"] == "canceled"
        mock_fatal.assert_not_called()


def test_execution_engine_cancel_live_host_blocked_in_paper_mode(monkeypatch, engine_with_live_host_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        engine_with_live_host_stub.cancel(broker_order_id="test_id")


def test_execution_engine_cancel_non_paper_mode_blocked(monkeypatch, engine_with_paper_alpaca_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(FatalExecutionPathError):
        engine_with_paper_alpaca_stub.cancel(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_paper_mode_allowed(monkeypatch, engine_with_paper_alpaca_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with patch("backend.common.runtime_execution_prevention.fatal_if_execution_reached") as mock_fatal:
        out = engine_with_paper_alpaca_stub.sync_and_ledger_if_filled(broker_order_id="test_id")
        assert out["status"] == "new"
        mock_fatal.assert_not_called()


def test_execution_engine_sync_and_ledger_if_filled_live_host_blocked_in_paper_mode(monkeypatch, engine_with_live_host_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    with pytest.raises(FatalExecutionPathError):
        engine_with_live_host_stub.sync_and_ledger_if_filled(broker_order_id="test_id")


def test_execution_engine_sync_and_ledger_if_filled_non_paper_mode_blocked(monkeypatch, engine_with_paper_alpaca_stub):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(FatalExecutionPathError):
        engine_with_paper_alpaca_stub.sync_and_ledger_if_filled(broker_order_id="test_id")


# --- Tests for Alpaca paper base URL safety boundary ---


def test_assert_paper_alpaca_base_url_accepts_paper_host_and_path():
    assert assert_paper_alpaca_base_url("https://paper-api.alpaca.markets/v2") == "https://paper-api.alpaca.markets/v2"
    assert assert_paper_alpaca_base_url("https://paper-api.alpaca.markets") == "https://paper-api.alpaca.markets"


def test_assert_paper_alpaca_base_url_rejects_live_host():
    with pytest.raises(RuntimeError, match="live Alpaca trading host is forbidden"):
        assert_paper_alpaca_base_url("https://api.alpaca.markets/v2")


def test_assert_paper_alpaca_base_url_rejects_http_scheme():
    with pytest.raises(RuntimeError, match="must be https"):
        assert_paper_alpaca_base_url("http://paper-api.alpaca.markets")


def test_assert_paper_alpaca_base_url_rejects_credentials():
    with pytest.raises(RuntimeError, match="must not include credentials"):
        assert_paper_alpaca_base_url("https://user:pass@paper-api.alpaca.markets")


def test_assert_paper_alpaca_base_url_rejects_port():
    with pytest.raises(RuntimeError, match="must not specify a port"):
        assert_paper_alpaca_base_url("https://paper-api.alpaca.markets:8080")


def test_assert_paper_alpaca_base_url_rejects_query_fragment():
    with pytest.raises(RuntimeError, match="must not include query/fragment"):
        assert_paper_alpaca_base_url("https://paper-api.alpaca.markets?query=param")


# --- Cooldown guard ---


def test_paper_execution_symbol_cooldown_blocks_rapid_retrade(monkeypatch, sample_intent):
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXEC_SYMBOL_COOLDOWN_S", "600")  # 10 minutes

    broker = _BrokerStub(
        alpaca_env=AlpacaEnv(
            key_id="k",
            secret_key="s",
            trading_host="https://paper-api.alpaca.markets",
            data_host="https://data.alpaca.markets",
        )
    )
    engine = ExecutionEngine(broker=broker, dry_run=False)

    # Avoid external dependencies in unit test: stub pre-trade assertions + risk manager.
    engine._assert_pre_trade = lambda *args, **kwargs: None  # type: ignore[method-assign]
    engine._risk.validate = lambda *args, **kwargs: RiskDecision(allowed=True, reason="ok", checks=[])  # type: ignore[method-assign]

    r1 = engine.execute_intent(intent=sample_intent)
    assert r1.status == "placed"
    assert broker.place_order_calls == 1

    r2 = engine.execute_intent(intent=sample_intent)
    assert r2.status == "rejected"
    assert r2.risk.allowed is False
    assert r2.risk.reason == "symbol_cooldown"
    assert broker.place_order_calls == 1  # second placement blocked
