
import os
import alpaca_trade_api as tradeapi
from firebase_admin import credentials, firestore, initialize_app

from backend.common.alpaca_env import configure_alpaca_env

def check_alpaca():
    """Checks the connection to Alpaca."""
    print("Checking Alpaca connection...")
    try:
        alpaca = configure_alpaca_env(required=True)
        api = tradeapi.REST(
            alpaca.api_key_id,
            alpaca.api_secret_key,
            base_url=alpaca.api_base_url,
            api_version="v2",
        )
        account = api.get_account()
        print(f"Alpaca connection successful. Account: {account.id}")
        return True
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
        initialize_app(cred)

        db = firestore.client()

        # Try to get a non-existent document
        doc_ref = db.collection('health_checks').document('non_existent_doc')
        doc_ref.get()

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
    main()
