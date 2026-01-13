import os

import pytest


def _dummy_alpaca_env(*, base_url: str):
    # Import inside helper to avoid import-time side effects in other tests.
    from backend.streams.alpaca_env import AlpacaEnv

    host = base_url.rstrip("/")
    return AlpacaEnv(
        key_id="test_key",
        secret_key="test_secret",
        trading_host=host,
        data_host="https://data.alpaca.markets",
    )


def _fatal_http_call(*, operation: str):
    from backend.common.runtime_execution_prevention import fatal_if_execution_reached

    fatal_if_execution_reached(
        operation=operation,
        explicit_message=f"HTTP execution reached unexpectedly: {operation}",
        context={"test": "regression_no_unguarded_trading_paths"},
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Keep tests deterministic: clear token env vars unless explicitly set by a test.
    for k in (
        "EXECUTION_CONFIRM_TOKEN",
        "EXECUTION_CONFIRM_TOKEN_PROVIDED",
        "X_EXEC_CONFIRM_TOKEN",
        "X_EXEC_CONFIRM_TOKEN_VALUE",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_alpaca_broker_place_order_fatals_without_confirm_token(monkeypatch):
    """
    Regression guard: there must be no path that can place a broker order without
    - agent_mode_guard (paper hard lock + forbidden agent modes)
    - kill switch check
    - execution confirm token
    """
    # Satisfy agent_mode_guard's startup contract so we test the confirm-token gate specifically.
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXECUTION_HALTED", "0")  # kill-switch off

    # No confirm token configured/provided => must fatal before any HTTP call.
    from backend.common.runtime_execution_prevention import FatalExecutionPathError

    import backend.execution.engine as eng

    monkeypatch.setattr(eng, "load_alpaca_env", lambda require_keys=True: _dummy_alpaca_env(base_url="https://paper-api.alpaca.markets"))
    monkeypatch.setattr(eng.requests, "post", lambda *a, **k: _fatal_http_call(operation="requests.post"))

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


def test_smoke_test_order_path_cannot_trade_without_confirm_token(monkeypatch):
    """
    Force an unexpected execution-capable entrypoint: the Alpaca order smoke test.
    It must not be able to submit an order without the confirm token gate.
    """
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXECUTION_HALTED", "0")
    monkeypatch.setenv("ENABLE_ALPACA_ORDER_SMOKE_TEST_ORDER", "true")

    # Satisfy load_alpaca_env() in the smoke test module import.
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test_secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    from backend.common.runtime_execution_prevention import FatalExecutionPathError

    import backend.execution.engine as eng

    monkeypatch.setattr(eng, "load_alpaca_env", lambda require_keys=True: _dummy_alpaca_env(base_url="https://paper-api.alpaca.markets"))
    monkeypatch.setattr(eng.requests, "post", lambda *a, **k: _fatal_http_call(operation="requests.post"))

    # Import after env + monkeypatching so module globals initialize safely.
    from backend.streams import alpaca_order_smoke_test as smoke

    with pytest.raises(FatalExecutionPathError, match="confirmation token"):
        smoke.place_test_order()

