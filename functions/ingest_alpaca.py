
import time
import random
import firebase_admin
from firebase_admin import credentials, firestore
from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod

# --- Initialize Firebase ---
cred = credentials.ApplicationDefault()
require_firestore_emulator_or_allow_prod(caller="functions.ingest_alpaca")
firebase_admin.initialize_app(cred)
db = firestore.client()

def-SECRET- add_trade_journal_entry(uid, ticker, price):
    """Adds a new trade journal entry to Firestore."""
    trade_ref = db.collection('users').document(uid).collection('tradeJournal').document()
    trade_ref.set({
        'ticker': ticker,
        'price': price,
        'uid': uid,
        'timestamp': firestore.SERVER_TIMESTAMP
    })
    print(f"Logged trade for {uid}: {ticker} @ {price}")

if __name__ == "__main__":
    print("Starting Alpaca ingest simulation...")
    users = [f"user_{i}" for i in range(1, 1001)]
    tickers = ["SPY", "QQQ", "AAPL", "GOOG", "MSFT"]

    while True:
        uid = random.choice(users)
        ticker = random.choice(tickers)
        price = round(random.uniform(100, 500), 2)
        add_trade_journal_entry(uid, ticker, price)
        time.sleep(5)
