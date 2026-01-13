import pytest


class _DummyAlpacaEnv:
    """
    Minimal stub for backend.streams.alpaca_env.AlpacaEnv as used by AlpacaBroker.
    We intentionally avoid reading real env vars in this regression test.
    """

    def __init__(self, *, trading_base_v2: str):
        self.key_id = "dummy_key"
        self.secret_key = "dummy_secret"
        self.trading_base_v2 = trading_base_v2


def _patch_all_alpaca_broker_http(monkeypatch, *, engine_module):
    """
    Monkeypatch all HTTP entry points used by AlpacaBroker so any accidental call
    is detected immediately.
    """
    http_calls: list[tuple[str, tuple, dict]] = []

    def _fail_http(name: str):
        def _inner(*args, **kwargs):
            http_calls.append((name, args, kwargs))
            raise AssertionError(
                f"REGRESSION: broker HTTP reached ({name}) before guards fired. "
                "This must be impossible in blocked execution paths."
            )

        return _inner

    # AlpacaBroker uses requests.{get,post,delete} today; patch request() as future-proofing.
    monkeypatch.setattr(engine_module.requests, "get", _fail_http("requests.get"), raising=True)
    monkeypatch.setattr(engine_module.requests, "post", _fail_http("requests.post"), raising=True)
    monkeypatch.setattr(engine_module.requests, "delete", _fail_http("requests.delete"), raising=True)
    monkeypatch.setattr(engine_module.requests, "request", _fail_http("requests.request"), raising=True)

    return http_calls


@pytest.mark.parametrize(
    "method_name, call_kwargs, expected_operation",
    [
        ("place_order", "intent", "alpaca.place_order"),
        ("cancel_order", "broker_order_id", "alpaca.cancel_order"),
        ("get_order_status", "broker_order_id", "alpaca.get_order_status"),
    ],
)
@pytest.mark.parametrize(
    "trading_mode, trading_base_v2",
    [
        # Unexpected execution path: not in paper mode, even with paper URL.
        ("live", "https://paper-api.alpaca.markets/v2"),
        # Unexpected execution path: paper mode but live URL injected.
        ("paper", "https://api.alpaca.markets/v2"),
    ],
)
def test_blocked_paths_never_reach_alpaca_broker_http(
    monkeypatch,
    method_name: str,
    call_kwargs: str,
    expected_operation: str,
    trading_mode: str,
    trading_base_v2: str,
):
    """
    Regression guard:
    No blocked runtime-execution path may reach broker HTTP calls.

    Method:
    - monkeypatch all AlpacaBroker HTTP methods (requests.* used by AlpacaBroker)
    - force unexpected execution paths (mode/url combinations)
    - assert fatal_if_execution_reached triggers (via raised FatalExecutionPathError)
    """
    import backend.execution.engine as engine
    from backend.common.runtime_execution_prevention import FatalExecutionPathError

    # Ensure broker construction is hermetic (no real env var requirements).
    monkeypatch.setattr(
        engine,
        "load_alpaca_env",
        lambda require_keys=True: _DummyAlpacaEnv(trading_base_v2="https://paper-api.alpaca.markets/v2"),
        raising=True,
    )

    # Keep this test focused on guard ordering: allow it to proceed to the fatal guard.
    monkeypatch.setattr(engine, "require_kill_switch_off", lambda **_: None, raising=True)

    http_calls = _patch_all_alpaca_broker_http(monkeypatch, engine_module=engine)

    # Spy on the guard: engine imports the symbol directly, so patch on the module.
    fatal_calls: list[dict] = []

    def _spy_fatal_if_execution_reached(*, operation: str, explicit_message: str, context=None):
        fatal_calls.append({"operation": operation, "explicit_message": explicit_message, "context": context})
        raise FatalExecutionPathError(explicit_message)

    monkeypatch.setattr(engine, "fatal_if_execution_reached", _spy_fatal_if_execution_reached, raising=True)

    monkeypatch.setenv("TRADING_MODE", trading_mode)

    broker = engine.AlpacaBroker(request_timeout_s=0.01)
    # Override runtime URL shape used for guard checks.
    broker._alpaca = _DummyAlpacaEnv(trading_base_v2=trading_base_v2)
    broker._base = trading_base_v2

    intent = engine.OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="test_account",
        symbol="SPY",
        side="buy",
        qty=1,
    )

    if call_kwargs == "intent":
        with pytest.raises(FatalExecutionPathError):
            getattr(broker, method_name)(intent=intent)
    else:
        with pytest.raises(FatalExecutionPathError):
            getattr(broker, method_name)(broker_order_id="test_order_id")

    # Guard must fire...
    assert len(fatal_calls) == 1
    assert fatal_calls[0]["operation"] == expected_operation
    # ...and absolutely no HTTP must be reached.
    assert http_calls == []

