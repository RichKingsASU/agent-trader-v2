import firebase_admin
from firebase_admin import credentials, firestore
import json

# Initialize
if not firebase_admin._apps:
    from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod
    require_firestore_emulator_or_allow_prod(caller="functions.verify_pipeline_data")
    firebase_admin.initialize_app()

db = firestore.client()

def verify_trade(uid, ticker):
    print(f"🔍 Searching for {ticker} trades for user: {uid}")
    
    # Query the subcollection
    docs = db.collection('users').document(uid).collection('tradeJournal').where('ticker', '==', ticker).stream()
    
    found = False
    for doc in docs:
        found = True
        print(f"✅ Found Document ID: {doc.id}")
        print(json.dumps(doc.to_dict(), indent=2, default=str))
    
    if not found:
        print(f"❌ No trades found for {ticker}. The function may not have triggered.")

if __name__ == "__main__":
    # Match the UID and Ticker from our previous injection test
    verify_trade("test-user-institutional-001", "NVDA")
