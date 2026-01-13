import pytest
from functions.utils.apca_env import assert_paper_alpaca_base_url


def _dummy_alpaca_env(*, base_url: str):
    from backend.streams.alpaca_env import AlpacaEnv

    host = base_url.rstrip("/")
    return AlpacaEnv(
        key_id="test_key",
        secret_key="test_secret",
        trading_host=host,
        data_host="https://data.alpaca.markets",
    )


def test_alpaca_broker_blocks_without_confirm_token(monkeypatch):
    """
    Safety regression: broker HTTP calls must be unreachable without an operator confirm token.
    """
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXECUTION_HALTED", "0")

    import backend.execution.engine as eng
    from backend.common.runtime_execution_prevention import FatalExecutionPathError

    # Avoid reading real env creds; avoid making real network calls.
    monkeypatch.setattr(
        eng, "load_alpaca_env", lambda require_keys=True: _dummy_alpaca_env(base_url="https://paper-api.alpaca.markets")
    )

    def _http_reached(*_a, **_k):
        raise AssertionError("HTTP call reached unexpectedly in unit test")

    monkeypatch.setattr(eng.requests, "post", _http_reached)
    monkeypatch.setattr(eng.requests, "delete", _http_reached)
    monkeypatch.setattr(eng.requests, "get", _http_reached)

    broker = eng.AlpacaBroker(request_timeout_s=0.01)
    intent = eng.OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="paper",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={},  # no exec_confirm_token
    )

    with pytest.raises(FatalExecutionPathError, match="confirmation token"):
        broker.place_order(intent=intent)

    with pytest.raises(FatalExecutionPathError, match="confirmation token"):
        broker.cancel_order(broker_order_id="test_id")

    with pytest.raises(FatalExecutionPathError, match="confirmation token"):
        broker.get_order_status(broker_order_id="test_id")


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
