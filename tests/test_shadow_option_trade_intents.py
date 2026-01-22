from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from backend.strategy_service.trade_intents import TradeRequest, shadow_option_fill_price


def test_shadow_option_fill_price_derives_premium_per_contract() -> None:
    # Notional is total premium; quantity is contracts; multiplier = 100.
    px = shadow_option_fill_price(notional=250.0, quantity=2.0)
    assert px == Decimal("1.2500")


def test_trade_request_option_requires_contract_fields_and_spy() -> None:
    with pytest.raises(Exception):
        TradeRequest(
            broker_account_id=uuid4(),
            strategy_id=uuid4(),
            symbol="AAPL",
            instrument_type="option",
            side="buy",
            order_type="market",
            notional=100.0,
            quantity=1.0,
        )

    req = TradeRequest(
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="option",
        side="buy",
        order_type="market",
        notional=100.0,
        quantity=1.0,
        contract_symbol="SPY240119C00450000",
        expiration="2024-01-19",
        strike=450.0,
        right="call",
    )
    assert req.symbol == "SPY"
    assert req.right == "call"

