from __future__ import annotations

import types

import pytest

from backend.common.agent_mode import AgentModeError
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.execution.engine import AlpacaBroker, ExecutionEngine, OrderIntent, RiskDecision


@pytest.mark.parametrize(
    "trading_mode, expect_exit_code",
    [
        (None, 13),
        ("", 13),
        ("live", 13),
        ("paper", None),
    ],
)
def test_enforce_agent_mode_guard_trading_mode_non_paper_fails_closed(
    monkeypatch, trading_mode: str | None, expect_exit_code: int | None
) -> None:
    """
    Invariant: startup must fail-closed unless TRADING_MODE=paper (paper hard lock).
    """
    monkeypatch.setenv("AGENT_MODE", "OFF")
    if trading_mode is None:
        monkeypatch.delenv("TRADING_MODE", raising=False)
    else:
        monkeypatch.setenv("TRADING_MODE", trading_mode)

    if expect_exit_code is not None:
        with pytest.raises(SystemExit) as e:
            enforce_agent_mode_guard()
        assert int(e.value.code) == expect_exit_code
    else:
        assert enforce_agent_mode_guard() == "OFF"


@pytest.mark.parametrize(
    "method_name, trading_mode, alpaca_trading_base_v2, expected_operation",
    [
        (
            "place_order",
            "live",
            "https://paper-api.alpaca.markets/v2",
            "alpaca.place_order",
        ),
        (
            "place_order",
            "paper",
            "https://api.alpaca.markets/v2",
            "alpaca.place_order",
        ),
        (
            "cancel_order",
            "live",
            "https://paper-api.alpaca.markets/v2",
            "alpaca.cancel_order",
        ),
        (
            "cancel_order",
            "paper",
            "https://api.alpaca.markets/v2",
            "alpaca.cancel_order",
        ),
        (
            "get_order_status",
            "live",
            "https://paper-api.alpaca.markets/v2",
            "alpaca.get_order_status",
        ),
        (
            "get_order_status",
            "paper",
            "https://api.alpaca.markets/v2",
            "alpaca.get_order_status",
        ),
    ],
)
def test_alpaca_broker_unauthorized_paths_always_trigger_fatal_execution_boundary(
    monkeypatch,
    method_name: str,
    trading_mode: str,
    alpaca_trading_base_v2: str,
    expected_operation: str,
) -> None:
    """
    Invariant: if paper-mode + paper-URL conditions are not BOTH satisfied,
    broker methods must route through fatal_if_execution_reached (fail-closed).
    """
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)

    # Avoid any env loading / network by constructing the broker instance directly.
    broker = AlpacaBroker.__new__(AlpacaBroker)
    broker._alpaca = types.SimpleNamespace(trading_base_v2=str(alpaca_trading_base_v2))  # type: ignore[attr-defined]
    broker._base = "https://example.invalid"  # type: ignore[attr-defined]
    broker._headers = {}  # type: ignore[attr-defined]
    broker._timeout = 0.001  # type: ignore[attr-defined]

    # Ensure we fail *before* any broker/network side effects regardless of config.
    called: dict[str, str] = {}

    def _fatal(*, operation: str, explicit_message: str, context=None):  # noqa: ANN001
        called["operation"] = str(operation)
        raise RuntimeError(explicit_message)

    import backend.execution.engine as engine_mod

    monkeypatch.setattr(engine_mod, "fatal_if_execution_reached", _fatal)
    monkeypatch.setattr(engine_mod, "require_kill_switch_off", lambda **_: None)

    if method_name == "place_order":
        fn = getattr(broker, method_name)
        with pytest.raises(RuntimeError):
            fn(
                intent=OrderIntent(
                    strategy_id="s1",
                    broker_account_id="acct1",
                    symbol="SPY",
                    side="buy",
                    qty=1,
                )
            )
    elif method_name in {"cancel_order", "get_order_status"}:
        fn = getattr(broker, method_name)
        with pytest.raises(RuntimeError):
            fn(broker_order_id="order_1")
    else:
        raise AssertionError(f"unhandled method_name: {method_name}")

    assert called.get("operation") == expected_operation


def test_execution_engine_refuses_broker_calls_without_live_authorization(monkeypatch) -> None:
    """
    Invariant: ExecutionEngine must not call broker methods unless AGENT_MODE=LIVE.
    """
    monkeypatch.setenv("AGENT_MODE", "DISABLED")
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)

    # Some deployments vendor helpers into the engine module; keep this test hermetic
    # by patching missing optional helpers to no-ops.
    import backend.execution.engine as engine_mod

    monkeypatch.setattr(engine_mod, "resolve_tenant_id_from_metadata", lambda _md: None, raising=False)
    monkeypatch.setattr(engine_mod, "NoopReservation", lambda: object(), raising=False)

    class _Broker:
        place_calls = 0
        cancel_calls = 0

        def place_order(self, *, intent):  # noqa: ARG002, ANN001
            self.place_calls += 1
            return {"id": "order_1", "status": "new", "filled_qty": "0"}

        def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
            self.cancel_calls += 1
            return {"id": broker_order_id, "status": "canceled"}

        def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
            raise AssertionError("should not be called in this test")

    class _RiskAllow:
        def validate(self, *, intent):  # noqa: ANN001, ARG002
            return RiskDecision(allowed=True, reason="ok")

    broker = _Broker()
    engine = ExecutionEngine(broker=broker, risk=_RiskAllow(), dry_run=False)

    with pytest.raises(AgentModeError):
        engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
            )
        )
    assert broker.place_calls == 0

    with pytest.raises(AgentModeError):
        engine.cancel(broker_order_id="order_1")
    assert broker.cancel_calls == 0

