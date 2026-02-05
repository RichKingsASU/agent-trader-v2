import firebase_admin
from firebase_admin import credentials, firestore, auth
import sys

# Initialize Firebase (uses ENV vars or ADC)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()

EMAIL = "test_admin@example.com"
TENANT_ID = "default"  # Assuming default tenant for now

ALPACA_KEY = "PKW647E5I3R6VUYLU46V6DFW4M"
ALPACA_SECRET = "HLJH85uZnxXQUinYmi83naRTeyNCAnonSzZN6szoR46X"

def save_secrets():
    print(f"Looking up user {EMAIL}...")
    try:
        user = auth.get_user_by_email(EMAIL)
        uid = user.uid
        print(f"Found user: {uid}")
    except Exception as e:
        print(f"Error finding user: {e}")
        return

    # Path 1: User Secrets (as seen in user_onboarding.py)
    # tenants/{tenantId}/users/{uid}/secrets/alpaca
    secret_path = f"tenants/{TENANT_ID}/users/{uid}/secrets/alpaca"
    print(f"Saving to {secret_path}...")
    
    doc_ref = db.document(secret_path)
    doc_ref.set({
        "key_id": ALPACA_KEY,
        "secret_key": ALPACA_SECRET,
        "configured": True,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)
    
    print("Secrets saved successfully!")

if __name__ == "__main__":
    save_secrets()
