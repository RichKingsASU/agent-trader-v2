from __future__ import annotations

from datetime import datetime, timezone
from datetime import date
from uuid import uuid4

from backend.contracts.v2.trading import OptionOrderIntent
from backend.contracts.v2.types import AssetClass, OrderType, Side, TimeInForce
from backend.trading.execution.shadow_options_executor import InMemoryShadowTradeHistoryStore, ShadowOptionsExecutor


def test_shadow_options_executor_stores_shadow_trade_and_returns_simulated_status() -> None:
    store = InMemoryShadowTradeHistoryStore()
    ex = ShadowOptionsExecutor(store=store)

    intent = OptionOrderIntent(
        schema="agenttrader.v2.option_order_intent",
        schema_version="2.0.0",
        tenant_id="t1",
        created_at=datetime.now(timezone.utc),
        intent_id=uuid4(),
        account_id="acct_1",
        strategy_id="strat_1",
        symbol="SPY",
        asset_class=AssetClass.option,
        side=Side.buy,
        order_type=OrderType.market,
        time_in_force=TimeInForce.day,
        # Shadow fill derivation: notional is total premium, quantity is contracts.
        notional="250",
        quantity="2",
        contract_symbol="SPY240119C00450000",
        expiration=date(2024, 1, 19),
        strike="450",
        right="call",
        options={"uid": "u1"},
    )

    out = ex.execute(intent=intent)

    assert out.status == "simulated"
    assert out.shadow_id

    stored = store.items[out.shadow_id]
    assert stored["intent_id"] == str(intent.intent_id)
    assert stored["contract_symbol"] == "SPY240119C00450000"
    assert stored["status"] == "OPEN"
    assert stored["execution_status"] == "simulated"
    # 250 / (2 * 100) = 1.25 per contract (quantized to 4dp)
    assert stored["entry_price"] == "1.2500"

