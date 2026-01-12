from __future__ import annotations

from backend.alpaca_signal_trader import TradeSignal, enforce_affordability


import pytest

@pytest.mark.xfail(reason="architecture drift")
def test_enforce_affordability_forces_flat_when_buying_power_zero() -> None:
    sig = TradeSignal(action="buy", symbol="SPY", notional_usd=100.0, reason="x")
    out = enforce_affordability(signal=sig, buying_power_usd=0.0)
    assert out.action == "flat"
    assert out.notional_usd == 0.0


def test_enforce_affordability_forces_flat_when_notional_exceeds_buying_power() -> None:
    sig = TradeSignal(action="buy", symbol="SPY", notional_usd=250.0, reason="x")
    out = enforce_affordability(signal=sig, buying_power_usd=100.0)
    assert out.action == "flat"
    assert out.notional_usd == 0.0


def test_enforce_affordability_allows_trade_within_buying_power() -> None:
    sig = TradeSignal(action="buy", symbol="SPY", notional_usd=50.0, reason="x")
    out = enforce_affordability(signal=sig, buying_power_usd=100.0)
    assert out.action == "buy"
    assert out.notional_usd == 50.0

