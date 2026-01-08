# agenttrader/scripts/validate_alpaca_account.py
import os
import sys
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.config.alpaca_env import load_alpaca_auth_env  # noqa: E402

def main():
    """
    Validates that the Alpaca paper trading account credentials are correct
    by fetching account information.
    """
    # Cloud Shell-safe: rely on exported env vars / Secret Manager injection.
    try:
        auth = load_alpaca_auth_env()
        api_key = auth.api_key_id
        secret_key = auth.api_secret_key
    except Exception:
        print("ERROR: Missing Alpaca creds. Set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and APCA_API_BASE_URL.")
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