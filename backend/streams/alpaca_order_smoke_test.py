import os
import requests
import json

from backend.config.alpaca_env import load_alpaca_auth_env

auth = load_alpaca_auth_env()
BASE = f"{auth.api_base_url}/v2"
HEADERS = auth.headers

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
