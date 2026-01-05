# agenttrader/scripts/validate_alpaca_account.py
import os
import sys
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key  # noqa: E402

def main():
    """
    Validates that the Alpaca paper trading account credentials are correct
    by fetching account information.
    """
    # Cloud Shell-safe: rely on exported env vars / Secret Manager injection.
    try:
        api_key = get_alpaca_key_id(required=True)
        secret_key = get_alpaca_secret_key(required=True)
    except Exception:
        print("ERROR: Missing Alpaca creds. Set ALPACA_KEY_ID and ALPACA_SECRET_KEY.")
        exit(1)

    print("--> Checking Alpaca paper account status...")
    try:
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/account",
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
            timeout=30,
        )
        r.raise_for_status()
        acct = r.json()
        # Safe fields (no secrets).
        print(f"    - Account ID: {acct.get('id')}")
        print(f"    - Status: {acct.get('status')}")
        print(f"    - Buying Power: {acct.get('buying_power')}")
        print("SUCCESS: Alpaca account connection is valid.")
    except Exception as e:
        # Don't print headers / secrets.
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status:
            print(f"ERROR: Failed to connect to Alpaca API (status={status}).")
        else:
            print("ERROR: Failed to connect to Alpaca API.")
        print(f"    - Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()