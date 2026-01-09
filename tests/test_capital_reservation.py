from __future__ import annotations

from decimal import Decimal

import pytest

from backend.risk.capital_reservation import (
    CapitalReservationState,
    DuplicateReservationError,
    InsufficientBuyingPowerError,
    ReleaseError,
    apply_release,
    apply_reserve,
)


def test_reserve_is_idempotent_by_trade_id_same_amount() -> None:
    s0 = CapitalReservationState.empty()
    s1, r1 = apply_reserve(state=s0, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))
    s2, r2 = apply_reserve(state=s1, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))
    assert s2.reserved_total_usd == Decimal("10.00")
    assert r1 == r2


def test_cannot_reserve_twice_with_different_amount() -> None:
    s0 = CapitalReservationState.empty()
    s1, _ = apply_reserve(state=s0, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))
    with pytest.raises(DuplicateReservationError):
        apply_reserve(state=s1, trade_id="t1", amount_usd=Decimal("11.00"), buying_power_usd=Decimal("100.00"))


def test_cannot_reserve_beyond_buying_power() -> None:
    s0 = CapitalReservationState.empty()
    with pytest.raises(InsufficientBuyingPowerError):
        apply_reserve(state=s0, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("5.00"))


def test_release_is_idempotent_by_trade_id() -> None:
    s0 = CapitalReservationState.empty()
    s1, _ = apply_reserve(state=s0, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))
    s2, r1 = apply_release(state=s1, trade_id="t1")
    s3, r2 = apply_release(state=s2, trade_id="t1")
    assert s2.reserved_total_usd == Decimal("0")
    assert s3.reserved_total_usd == Decimal("0")
    assert r1.trade_id == "t1"
    assert r2.state == "released"


def test_cannot_release_without_reservation() -> None:
    s0 = CapitalReservationState.empty()
    with pytest.raises(ReleaseError):
        apply_release(state=s0, trade_id="missing")


def test_cannot_reserve_after_release() -> None:
    s0 = CapitalReservationState.empty()
    s1, _ = apply_reserve(state=s0, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))
    s2, _ = apply_release(state=s1, trade_id="t1")
    with pytest.raises(DuplicateReservationError):
        apply_reserve(state=s2, trade_id="t1", amount_usd=Decimal("10.00"), buying_power_usd=Decimal("100.00"))

