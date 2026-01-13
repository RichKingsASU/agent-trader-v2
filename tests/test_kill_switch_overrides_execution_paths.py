from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from backend.common.execution_confirm import require_confirm_token_for_live_execution
from backend.common.runtime_execution_prevention import FatalExecutionPathError
from backend.execution.engine import AlpacaBroker, ExecutionEngine, OrderIntent, RiskConfig, RiskManager
from backend.streams.alpaca_env import AlpacaEnv


class _LedgerStub:
    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return 0

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        raise AssertionError("ledger writes must not occur in kill-switch tests")


class _PositionsStub:
    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return 0.0


@dataclass
class _BrokerStub:
    place_order: MagicMock
    cancel_order: MagicMock
    get_order_status: MagicMock


def _risk_allow() -> RiskManager:
    return RiskManager(
        config=RiskConfig(max_position_qty=10_000, max_daily_trades=10_000, fail_open=True),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )


def _alpaca_broker_without_init(*, trading_host: str) -> AlpacaBroker:
    """
    Construct AlpacaBroker without reading real env keys in __init__.
    We only care that kill-switch fires before any HTTP calls.
    """
    b = AlpacaBroker.__new__(AlpacaBroker)
    b._alpaca = AlpacaEnv(
        key_id="k",
        secret_key="s",
        trading_host=trading_host,
        data_host="https://data.alpaca.markets",
    )
    b._base = b._alpaca.trading_base_v2
    b._headers = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}
    b._timeout = 1.0
    return b


@pytest.mark.parametrize(
    "trading_mode,alpaca_host",
    [
        ("paper", "https://paper-api.alpaca.markets"),
        ("live", "https://api.alpaca.markets"),
    ],
)
def test_kill_switch_blocks_alpaca_broker_place_order_before_http(monkeypatch, trading_mode: str, alpaca_host: str):
    """
    EXECUTION_HALTED=1 must block BOTH:
    - paper execution (TRADING_MODE=paper + paper host)
    - live execution (TRADING_MODE=live + live host)

    Assertion: fatal boundary triggers AND no HTTP/broker call occurs.
    """
    monkeypatch.setenv("EXECUTION_HALTED", "1")
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "ok")

    # "Valid" token present (kill-switch must still win).
    require_confirm_token_for_live_execution(provided_token="ok")

    broker = _alpaca_broker_without_init(trading_host=alpaca_host)
    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
    )

    with patch("backend.execution.engine.requests.post") as post_mock:
        with pytest.raises(FatalExecutionPathError):
            broker.place_order(intent=intent)
        post_mock.assert_not_called()


@pytest.mark.parametrize("trading_mode", ["paper", "live"])
def test_kill_switch_blocks_execution_engine_paths_and_prevents_broker_calls(monkeypatch, trading_mode: str):
    """
    Prove kill-switch overrides the *engine* execution paths (place, cancel, status poll),
    even when "live" flags/tokens are set.
    """
    monkeypatch.setenv("EXECUTION_HALTED", "1")
    monkeypatch.setenv("TRADING_MODE", trading_mode)
    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "ok")

    # Token gate would pass; kill-switch must still hard-stop.
    require_confirm_token_for_live_execution(provided_token="ok")

    broker = _BrokerStub(
        place_order=MagicMock(name="place_order"),
        cancel_order=MagicMock(name="cancel_order"),
        get_order_status=MagicMock(name="get_order_status"),
    )
    engine = ExecutionEngine(broker=broker, risk=_risk_allow(), dry_run=False)

    intent = OrderIntent(
        strategy_id="s1",
        broker_account_id="acct1",
        symbol="SPY",
        side="buy",
        qty=1,
    )

    with pytest.raises(FatalExecutionPathError):
        engine.execute_intent(intent=intent)
    broker.place_order.assert_not_called()

    with pytest.raises(FatalExecutionPathError):
        engine.cancel(broker_order_id="order_1")
    broker.cancel_order.assert_not_called()

    with pytest.raises(FatalExecutionPathError):
        engine.sync_and_ledger_if_filled(broker_order_id="order_1")
    broker.get_order_status.assert_not_called()

