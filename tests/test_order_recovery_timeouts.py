from datetime import datetime, timedelta, timezone

from backend.execution.order_recovery import (
    TimeoutRules,
    infer_asset_class,
    is_open_status,
    is_terminal_status,
    is_stale_for_poll,
    is_unfilled_past_timeout,
    timeout_seconds_for_intent,
)


def test_infer_asset_class_from_metadata() -> None:
    assert infer_asset_class(metadata={"asset_class": "OPTIONS"}) == "OPTIONS"
    assert infer_asset_class(metadata={"asset_class": " options "}) == "OPTIONS"
    assert infer_asset_class(metadata={"instrument_type": "option"}) == "OPTIONS"
    assert infer_asset_class(metadata={"instrument_type": "stock"}) == "EQUITY"
    assert infer_asset_class(metadata={}) == "EQUITY"


def test_timeout_selection() -> None:
    rules = TimeoutRules(
        options_market_s=21,
        options_limit_s=121,
        default_market_s=11,
        default_limit_s=91,
        stale_s=60,
    )
    assert timeout_seconds_for_intent(asset_class="OPTIONS", order_type="market", rules=rules) == 21
    assert timeout_seconds_for_intent(asset_class="OPTIONS", order_type="limit", rules=rules) == 121
    assert timeout_seconds_for_intent(asset_class="EQUITY", order_type="market", rules=rules) == 11
    assert timeout_seconds_for_intent(asset_class="EQUITY", order_type="stop_limit", rules=rules) == 91


def test_status_sets() -> None:
    assert is_open_status("new")
    assert is_open_status("PARTIALLY_FILLED")
    assert is_terminal_status("filled")
    assert is_terminal_status("canceled")
    assert not is_terminal_status("accepted")


def test_stale_and_timeout_checks() -> None:
    rules = TimeoutRules.from_env()
    now = datetime.now(timezone.utc)
    assert is_stale_for_poll(now=now, last_broker_sync_at=None, rules=rules) is True
    assert is_stale_for_poll(now=now, last_broker_sync_at=now - timedelta(seconds=rules.stale_s + 1), rules=rules) is True
    assert is_stale_for_poll(now=now, last_broker_sync_at=now - timedelta(seconds=1), rules=rules) is False

    created = now - timedelta(seconds=10)
    assert is_unfilled_past_timeout(now=now, created_at=created, timeout_s=5) is True
    assert is_unfilled_past_timeout(now=now, created_at=created, timeout_s=15) is False

