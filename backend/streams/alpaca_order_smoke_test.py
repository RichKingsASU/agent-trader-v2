import os
import requests
import json

from backend.streams.alpaca_env import load_alpaca_env

alpaca = load_alpaca_env()
BASE = alpaca.trading_base_v2
KEY = alpaca.key_id
SEC = alpaca.secret_key
HEADERS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}

def check_account():
    """Checks Alpaca account status."""
    print("Checking Alpaca account...")
    r = requests.get(f"{BASE}/account", headers=HEADERS)
    r.raise_for_status()
    account_info = r.json()
    print(f"  Status: {account_info.get('status')}")
    print(f"  Buying Power: {account_info.get('buying_power')}")

def place_test_order():
    """Places a test paper order."""
    print("\nPlacing test order...")
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
    print(f"  Order ID: {order_info.get('id')}")
    print(f"  Status: {order_info.get('status')}")
    print(f"  Filled Qty: {order_info.get('filled_qty')}")

if __name__ == "__main__":
    check_account()
    # To place a real test paper order, uncomment the following line:
    # place_test_order()
