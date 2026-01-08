import os
import requests
import json
import logging

from backend.streams.alpaca_env import load_alpaca_env
from backend.common.logging import init_structured_logging

init_structured_logging(service="alpaca-order-smoke-test")
logger = logging.getLogger(__name__)

alpaca = load_alpaca_env()
BASE = alpaca.trading_base_v2
KEY = alpaca.key_id
SEC = alpaca.secret_key
HEADERS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}

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
    logger.warning("Placing test order...", extra={"event_type": "alpaca.place_test_order"})
    payload = {
        "symbol": "SPY",
        "qty": "1",
        "side": "buy",
        "type": "market",
        "time_in_force": "day"
    }
    r = requests.post(f"{BASE}/orders", headers=HEADERS, json=payload)
    r.raise_for_status()
    order_info = r.json()
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
