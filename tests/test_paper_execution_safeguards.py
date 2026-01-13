from __future__ import annotations

from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from backend.common.runtime_execution_prevention import FatalExecutionPathError, fatal_if_execution_reached
from backend.execution.engine import AlpacaBroker, OrderIntent


@pytest.fixture(autouse=True)
def _ensure_kill_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # Broker methods call the kill switch guard first; keep it off for unit tests.
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
    monkeypatch.delenv("EXECUTION_HALTED_FILE", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH_FILE", raising=False)


@pytest.fixture
def sample_intent() -> OrderIntent:
    return OrderIntent(
        strategy_id="test_strategy",
        broker_account_id="test_account",
        symbol="SPY",
        side="buy",
        qty=1,
    )


def _set_alpaca_env(monkeypatch: pytest.MonkeyPatch, *, base_url: str) -> None:
    # Alpaca broker loads these via backend.common.env helpers.
    monkeypatch.setenv("APCA_API_KEY_ID", "unit_test_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "unit_test_secret")
    monkeypatch.setenv("APCA_API_BASE_URL", base_url)


def _mk_ok_response(*, json_body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = json_body
    return r


def test_fatal_if_execution_reached_always_raises_and_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even if environment looks like paper, fatal_if_execution_reached itself must always raise.
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    msg = "do not cross this boundary"
    with pytest.raises(FatalExecutionPathError) as ei:
        fatal_if_execution_reached(operation="unit.test", explicit_message=msg, context={"a": 1})

    assert str(ei.value) == msg


@pytest.mark.parametrize(
    "trading_mode, apca_base_url, should_bypass",
    [
        ("paper", "https://paper-api.alpaca.markets", True),
        ("paper", "https://paper-api.alpaca.markets/v2", True),
        ("live", "https://paper-api.alpaca.markets", False),
        ("", "https://paper-api.alpaca.markets", False),
        ("paper", "https://PAPER-api.alpaca.markets", False),  # case-sensitive substring check in implementation
    ],
)
def test_alpaca_place_order_http_call_only_when_paper_bypass_conditions_met(
    monkeypatch: pytest.MonkeyPatch,
    sample_intent: OrderIntent,
    trading_mode: str,
    apca_base_url: str,
    should_bypass: bool,
) -> None:
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    _set_alpaca_env(monkeypatch, base_url=apca_base_url)

    broker = AlpacaBroker(request_timeout_s=0.01)

    expected_msg = (
        "Runtime execution is forbidden in agent-trader-v2. "
        "A broker submission attempt reached AlpacaBroker.place_order; aborting."
    )

    post_mock = MagicMock(return_value=_mk_ok_response(json_body={"id": "order_1", "status": "new"}))
    delete_mock = MagicMock()
    get_mock = MagicMock()

    if should_bypass:
        with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not be called")):
            with patch("backend.execution.engine.requests.post", post_mock), patch(
                "backend.execution.engine.requests.delete", delete_mock
            ), patch("backend.execution.engine.requests.get", get_mock):
                out = broker.place_order(intent=sample_intent)
        assert out["id"] == "order_1"
        post_mock.assert_called_once()
        delete_mock.assert_not_called()
        get_mock.assert_not_called()
    else:
        with patch("backend.execution.engine.requests.post", post_mock), patch(
            "backend.execution.engine.requests.delete", delete_mock
        ), patch("backend.execution.engine.requests.get", get_mock):
            with pytest.raises(FatalExecutionPathError) as ei:
                broker.place_order(intent=sample_intent)
        assert str(ei.value) == expected_msg
        post_mock.assert_not_called()
        delete_mock.assert_not_called()
        get_mock.assert_not_called()


@pytest.mark.parametrize(
    "trading_mode, apca_base_url, should_bypass",
    [
        ("paper", "https://paper-api.alpaca.markets", True),
        ("live", "https://paper-api.alpaca.markets", False),
        ("paper", "https://PAPER-api.alpaca.markets", False),  # passes env validation; fails substring check
    ],
)
def test_alpaca_cancel_order_http_call_only_when_paper_bypass_conditions_met(
    monkeypatch: pytest.MonkeyPatch,
    trading_mode: str,
    apca_base_url: str,
    should_bypass: bool,
) -> None:
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    _set_alpaca_env(monkeypatch, base_url=apca_base_url)

    broker = AlpacaBroker(request_timeout_s=0.01)
    expected_msg = (
        "Runtime execution is forbidden in agent-trader-v2. "
        "A broker cancel attempt reached AlpacaBroker.cancel_order; aborting."
    )

    delete_resp = MagicMock()
    delete_resp.status_code = 204
    delete_resp.raise_for_status.return_value = None

    post_mock = MagicMock()
    delete_mock = MagicMock(return_value=delete_resp)
    get_mock = MagicMock()

    if should_bypass:
        with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not be called")):
            with patch("backend.execution.engine.requests.post", post_mock), patch(
                "backend.execution.engine.requests.delete", delete_mock
            ), patch("backend.execution.engine.requests.get", get_mock):
                out = broker.cancel_order(broker_order_id="order_123")
        assert out == {"id": "order_123", "status": "canceled"}
        delete_mock.assert_called_once()
        post_mock.assert_not_called()
        get_mock.assert_not_called()
    else:
        with patch("backend.execution.engine.requests.post", post_mock), patch(
            "backend.execution.engine.requests.delete", delete_mock
        ), patch("backend.execution.engine.requests.get", get_mock):
            with pytest.raises(FatalExecutionPathError) as ei:
                broker.cancel_order(broker_order_id="order_123")
        assert str(ei.value) == expected_msg
        post_mock.assert_not_called()
        delete_mock.assert_not_called()
        get_mock.assert_not_called()


@pytest.mark.parametrize(
    "trading_mode, apca_base_url, should_bypass",
    [
        ("paper", "https://paper-api.alpaca.markets", True),
        ("live", "https://paper-api.alpaca.markets", False),
        ("paper", "https://PAPER-api.alpaca.markets", False),  # passes env validation; fails substring check
    ],
)
def test_alpaca_get_order_status_http_call_only_when_paper_bypass_conditions_met(
    monkeypatch: pytest.MonkeyPatch,
    trading_mode: str,
    apca_base_url: str,
    should_bypass: bool,
) -> None:
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    _set_alpaca_env(monkeypatch, base_url=apca_base_url)

    broker = AlpacaBroker(request_timeout_s=0.01)
    expected_msg = (
        "Runtime execution is forbidden in agent-trader-v2. "
        "A broker status poll reached AlpacaBroker.get_order_status; aborting."
    )

    post_mock = MagicMock()
    delete_mock = MagicMock()
    get_mock = MagicMock(return_value=_mk_ok_response(json_body={"id": "order_123", "status": "new"}))

    if should_bypass:
        with patch("backend.execution.engine.fatal_if_execution_reached", side_effect=AssertionError("fatal should not be called")):
            with patch("backend.execution.engine.requests.post", post_mock), patch(
                "backend.execution.engine.requests.delete", delete_mock
            ), patch("backend.execution.engine.requests.get", get_mock):
                out = broker.get_order_status(broker_order_id="order_123")
        assert out["id"] == "order_123"
        get_mock.assert_called_once()
        post_mock.assert_not_called()
        delete_mock.assert_not_called()
    else:
        with patch("backend.execution.engine.requests.post", post_mock), patch(
            "backend.execution.engine.requests.delete", delete_mock
        ), patch("backend.execution.engine.requests.get", get_mock):
            with pytest.raises(FatalExecutionPathError) as ei:
                broker.get_order_status(broker_order_id="order_123")
        assert str(ei.value) == expected_msg
        post_mock.assert_not_called()
        delete_mock.assert_not_called()
        get_mock.assert_not_called()
