from __future__ import annotations

from datetime import date

import pytest

from backend.trading.option_order_intent import OptionOrderIntent, OptionType, OrderSide


def test_option_order_intent_normalizes_and_serializes() -> None:
    oi = OptionOrderIntent(
        symbol=" spy ",
        option_type="call",
        strike=500.0,
        expiry=date(2026, 1, 17),
        side="buy",
        quantity=2,
        reason=" mean reversion ",
        strategy_id="gamma_scalper",
    )
    assert oi.symbol == "SPY"
    assert oi.option_type is OptionType.CALL
    assert oi.side is OrderSide.BUY
    assert oi.reason == "mean reversion"
    assert oi.strategy_id == "gamma_scalper"

    d = oi.to_dict()
    assert d["symbol"] == "SPY"
    assert d["option_type"] == "CALL"
    assert d["side"] == "BUY"
    assert d["expiry"] == "2026-01-17"

    oi2 = OptionOrderIntent.from_dict(d)
    assert oi2 == oi


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"symbol": "", "reason": "x", "strategy_id": "s"}, "symbol must be a non-empty string"),
        ({"symbol": "SPY", "option_type": "NOPE", "reason": "x", "strategy_id": "s"}, "option_type must be CALL or PUT"),
        ({"symbol": "SPY", "side": "NOPE", "reason": "x", "strategy_id": "s"}, "side must be BUY or SELL"),
        ({"symbol": "SPY", "strike": -1.0, "reason": "x", "strategy_id": "s"}, "strike must be a finite positive number"),
        ({"symbol": "SPY", "quantity": 0, "reason": "x", "strategy_id": "s"}, "quantity must be a positive integer"),
        ({"symbol": "SPY", "reason": "   ", "strategy_id": "s"}, "reason must be a non-empty string"),
        ({"symbol": "SPY", "reason": "x", "strategy_id": "   "}, "strategy_id must be a non-empty string"),
    ],
)
def test_option_order_intent_rejects_invalid_inputs(kwargs: dict, expected: str) -> None:
    base = dict(
        symbol="SPY",
        option_type="CALL",
        strike=500.0,
        expiry=date(2026, 1, 17),
        side="BUY",
        quantity=1,
        reason="test",
        strategy_id="s",
    )
    base.update(kwargs)
    with pytest.raises((ValueError, TypeError)) as e:
        OptionOrderIntent(**base)  # type: ignore[arg-type]
    assert expected in str(e.value)

