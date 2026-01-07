from __future__ import annotations

from backend.ops.status_contract import (
    REASON_KILL_SWITCH,
    REASON_MARKET_CLOSED,
    REASON_MARKETDATA_STALE,
    REASON_REQUIRED_FIELDS_MISSING,
    compute_ops_state,
)


def test_kill_switch_halted() -> None:
    state, reasons = compute_ops_state(
        service_kind="marketdata",
        process_up=True,
        kill_switch=True,
        market_is_open=True,
        required_fields_present=True,
        marketdata_is_fresh=True,
    )
    assert state == "HALTED"
    assert reasons == [REASON_KILL_SWITCH]


def test_market_closed_is_market_closed_not_degraded() -> None:
    state, reasons = compute_ops_state(
        service_kind="marketdata",
        process_up=True,
        kill_switch=False,
        market_is_open=False,
        required_fields_present=True,
        marketdata_is_fresh=False,  # should be ignored after-hours
    )
    assert state == "MARKET_CLOSED"
    assert reasons == [REASON_MARKET_CLOSED]


def test_stale_marketdata_market_hours_marketdata_is_degraded() -> None:
    state, reasons = compute_ops_state(
        service_kind="marketdata",
        process_up=True,
        kill_switch=False,
        market_is_open=True,
        required_fields_present=True,
        marketdata_is_fresh=False,
    )
    assert state == "DEGRADED"
    assert reasons == [REASON_MARKETDATA_STALE]


def test_stale_marketdata_market_hours_strategy_is_halted() -> None:
    state, reasons = compute_ops_state(
        service_kind="strategy",
        process_up=True,
        kill_switch=False,
        market_is_open=True,
        required_fields_present=True,
        marketdata_is_fresh=False,
    )
    assert state == "HALTED"
    assert reasons == [REASON_MARKETDATA_STALE]


def test_missing_required_fields_unknown() -> None:
    state, reasons = compute_ops_state(
        service_kind="marketdata",
        process_up=True,
        kill_switch=False,
        market_is_open=True,
        required_fields_present=False,
    )
    assert state == "UNKNOWN"
    assert reasons == [REASON_REQUIRED_FIELDS_MISSING]

