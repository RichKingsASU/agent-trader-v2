import os
import requests
import json
import logging

from backend.streams.alpaca_env import load_alpaca_env
from backend.common.logging import init_structured_logging
from backend.execution.engine import AlpacaBroker, OrderIntent

init_structured_logging(service="alpaca-order-smoke-test")
logger = logging.getLogger(__name__)

alpaca = load_alpaca_env()
BASE = alpaca.trading_base_v2
KEY = alpaca.key_id
SEC = alpaca.secret_key
HEADERS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}


def _require_explicit_order_smoke_test_override() -> None:
    """
    This module is execution-capable (order placement). Refuse by default.
    """
    v = (os.getenv("ENABLE_ALPACA_ORDER_SMOKE_TEST_ORDER") or "").strip().lower()
    if v not in {"1", "true", "t", "yes", "y", "on"}:
        raise RuntimeError(
            "REFUSED: alpaca_order_smoke_test order placement is disabled by default. "
            "Set ENABLE_ALPACA_ORDER_SMOKE_TEST_ORDER=true to allow placing a test order."
        )


def check_account():
    """Checks Alpaca account status."""
    logger.info("Checking Alpaca account...", extra={"event_type": "alpaca.account_check"})
    r = requests.get(f"{BASE}/account", headers=HEADERS)
    r.raise_for_status()
    account_info = r.json()
    logger.info(
        "Alpaca account status",
        extra={
            "event_type": "alpaca.account_status",
            "status": account_info.get("status"),
            "buying_power": account_info.get("buying_power"),
        },
    )

def place_test_order():
    """Places a test paper order."""
    _require_explicit_order_smoke_test_override()

    is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
    is_alpaca_paper_url = "paper-api.alpaca.markets" in alpaca.trading_base_v2

    if not (is_paper_mode and is_alpaca_paper_url):
        raise RuntimeError(
            "REFUSED: Test order placement is only allowed in paper trading mode "
            "with Alpaca paper API. "
            f"(TRADING_MODE='{os.getenv('TRADING_MODE')}', "
            f"APCA_API_BASE_URL='{alpaca.trading_base_v2}')"
        )

    logger.warning("Placing test order...", extra={"event_type": "alpaca.place_test_order"})
    broker = AlpacaBroker(request_timeout_s=10.0)
    intent = OrderIntent(
        strategy_id="alpaca_order_smoke_test",
        broker_account_id="paper",
        symbol="SPY",
        side="buy",
        qty=1,
        order_type="market",
        time_in_force="day",
        metadata={
            # Provide the confirm token via env if you intend to run this script.
            # - Expected: EXECUTION_CONFIRM_TOKEN
            # - Provided: EXECUTION_CONFIRM_TOKEN_PROVIDED
            "source": "alpaca_order_smoke_test",
        },
    )
    order_info = broker.place_order(intent=intent)
    logger.info(
        "Test order result",
        extra={
            "event_type": "alpaca.test_order_result",
            "order_id": order_info.get("id"),
            "status": order_info.get("status"),
            "filled_qty": order_info.get("filled_qty"),
        },
    )

if __name__ == "__main__":
    check_account()
    # To place a real test paper order, uncomment the following line:
    # place_test_order()
