import os
import firebase_admin
from firebase_admin import credentials, firestore
import google.cloud.aiplatform as aip
import random
import time
from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod

# --- Configuration ---
PROJECT_ID = os.environ.get("GCLOUD_PROJECT", "agenttrader-prod")
LOCATION = "us-central1"
MODEL_NAME = "gemini-1.5-pro-001"

# --- Initialize Firebase ---
cred = credentials.ApplicationDefault()
require_firestore_emulator_or_allow_prod(caller="functions.run_gemini_analysis")
firebase_admin.initialize_app(cred, {
    'projectId': PROJECT_ID,
})
db = firestore.client()

# --- Initialize Vertex AI ---
aip.init(project=PROJECT_ID, location=LOCATION)
model = aip.GenerativeModel(MODEL_NAME)

def get_recent_gex_data(ticker):
    """Fetches the most recent GEX data for a ticker from Firestore."""
    gex_ref = db.collection('gex_data').where('ticker', '==', ticker).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1).stream()
    for doc in gex_ref:
        return doc.to_dict()
    return None

def calculate_mock_sharpe_ratio():
    """Calculates a mock Sharpe Ratio."""
    # In a real scenario, this would involve fetching historical returns,
    # risk-free rate, and calculating standard deviation.
    # Here, we'll just generate a random number.
    return round(random.uniform(0.5, 2.5), 2)

def process_trade(doc_snapshot, doc_path):
    """Callback function to process a new trade document."""
    try:
        trade_data = doc_snapshot.to_dict()
        if not trade_data:
            print(f"Empty document snapshot received for {doc_path}")
            return

        ticker = trade_data.get('ticker')
        price = trade_data.get('price')
        uid = trade_data.get('uid')

        if not all([ticker, price, uid]):
            print(f"Incomplete trade data in {doc_path}: {trade_data}")
            return

        print(f"New trade detected for user {uid}: {ticker} @ {price}")

        gex_data = get_recent_gex_data(ticker)
        if not gex_data:
            print(f"No GEX data found for {ticker}")
            return

        prompt = f"""
        Analyze the following trade in the context of the latest Gamma Exposure (GEX) data.

        **Trade Details:**
        - Ticker: {ticker}
        - Price: {price}

        **GEX Data:**
        - Net GEX: {gex_data.get('net_gex')}
        - Volatility Bias: {gex_data.get('volatility_bias')}

        **Instructions:**
        Provide a concise journal entry (2-3 sentences) analyzing whether this trade aligns with or contradicts the market sentiment suggested by the GEX data. For example, if GEX indicates a bullish sentiment, a long position would be aligned.
        """

        response = model.generate_content(prompt)
        journal_entry = response.text

        # --- Update Trade Journal with AI Analysis ---
        trade_ref = db.document(doc_path)
        trade_ref.update({'ai_journal': journal_entry})
        print(f"Successfully generated journal entry for trade {doc_path}")

        # --- Calculate Mock Sharpe Ratio and Update User Stats ---
        sharpe_ratio = calculate_mock_sharpe_ratio()
        user_stats_ref = db.collection('userStats').document(uid)
        user_stats_ref.set({'mock_sharpe_ratio': sharpe_ratio}, merge=True)
        print(f"Updated mock Sharpe Ratio for user {uid}: {sharpe_ratio}")

    except Exception as e:
        print(f"Error processing trade {doc_path}: {e}")


def on_snapshot(col_snapshot, changes, read_time):
    """Watch for new documents in the tradeJournal collection group."""
    for change in changes:
        if change.type.name == 'ADDED':
            process_trade(change.document, change.document.reference.path)

if __name__ == "__main__":
    print("Starting trade journal listener...")
    trade_journal_query = db.collection_group('tradeJournal')
    query_watch = trade_journal_query.on_snapshot(on_snapshot)

    # Keep the script running
    while True:
        time.sleep(1)