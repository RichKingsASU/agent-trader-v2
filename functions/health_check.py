import os
import datetime
import logging
from typing import Any, Dict, Optional

# Standardize on alpaca-py
# Remove direct import of alpaca_trade_api
# import alpaca_trade_api as tradeapi
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError # For catching Alpaca API errors

from firebase_admin import credentials, firestore, initialize_app

from functions.utils.apca_env import assert_paper_alpaca_base_url

logger = logging.getLogger(__name__)

def check_alpaca():
    """Checks the connection to Alpaca using TradingClient from alpaca-py."""
    print("Checking Alpaca connection...")
    
    api_key = os.environ.get('APCA_API_KEY_ID')
    secret_key = os.environ.get('APCA_API_SECRET_KEY')
    base_url = assert_paper_alpaca_base_url(
        os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
    )

    if not api_key or not secret_key:
        print("Alpaca API keys not found. Please set the APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables.")
        return False
        
    try:
        client = TradingClient(
            key_id=api_key,
            secret_key=secret_key,
            base_url=base_url
        )
        # Attempt a simple call to verify connection, e.g., get account info
        account = client.get_account()
        print(f"Alpaca connection successful. Account: {account.id}")
        return True
    except APIError as e:
        print(f"Alpaca API error during health check: {e.message} (Code: {e.code}, Status: {e.status})")
        return False
    except Exception as e:
        print(f"Alpaca connection failed: {e}")
        return False

def check_firestore():
    """Checks the connection to Firestore."""
    print("Checking Firestore connection...")
    try:
        # Initialize the app with a service account, granting admin privileges
        if not os.path.exists('serviceAccountKey.json'):
            print('serviceAccountKey.json not found. Please add the file to the functions folder')
            return False
            
        cred = credentials.Certificate("serviceAccountKey.json")
        # Ensure Firebase app is initialized only once
        if not firebase_admin._apps:
            initialize_app(cred)
        
        db = firestore.client()

        # Try to get a non-existent document to check read permissions/connection
        doc_ref = db.collection('health_checks').document('non_existent_doc_check')
        doc_ref.get() # This operation checks connection and permissions

        print("Firestore connection successful.")
        return True
    except Exception as e:
        print(f"Firestore connection failed: {e}")
        return False


def main():
    """Main function for the health check."""
    print("Running health checks...")
    alpaca_ok = check_alpaca()
    firestore_ok = check_firestore()

    if alpaca_ok and firestore_ok:
        print("All health checks passed.")
    else:
        print("One or more health checks failed.")

if __name__ == "__main__":
    # Set dummy environment variables for example run if not set
    if not os.environ.get("APCA_API_KEY_ID"): os.environ["APCA_API_KEY_ID"] = "DUMMY_KEY_ID_HEALTH_CHECK"
    if not os.environ.get("APCA_API_SECRET_KEY"): os.environ["APCA_API_SECRET_KEY"] = "DUMMY_SECRET_KEY_HEALTH_CHECK"
    if not os.environ.get("APCA_API_BASE_URL"): os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    
    main()

    # Clean up dummy environment variables
    for var in ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"]:
        if var in os.environ:
            del os.environ[var]