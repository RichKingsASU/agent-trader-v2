import asyncio
import os
import json
from datetime import datetime, timezone
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import (
    map_devconsole_news,
    map_devconsole_options_flow,
    map_devconsole_account_update
)

async def main():
    """
    Local smoke test for the Stream Bridge: loads fixtures, maps them, and writes to Firestore.
    """
    print("Running Stream Bridge local test harness...")
    writer = await FirestoreWriter.create_from_env()

    # --- Test News Events ---
    print("Testing news events...")
    with open("backend/streams_bridge/fixtures/news_sample.json", 'r') as f:
        news_payload = json.load(f)
    news_event = map_devconsole_news(news_payload)
    await writer.insert_news_events([news_event])
    print("  Inserted 1 sample news event.")

    # --- Test Options Flow ---
    print("Testing options flow...")
    with open("backend/streams_bridge/fixtures/options_flow_sample.json", 'r') as f:
        options_flow_payload = json.load(f)
    options_flow_event = map_devconsole_options_flow(options_flow_payload)
    await writer.insert_options_flow([options_flow_event])
    print("  Inserted 1 sample options flow event.")

    # --- Test Account Updates ---
    print("Testing account updates...")
    with open("backend/streams_bridge/fixtures/account_update_sample.json", 'r') as f:
        account_update_payload = json.load(f)
    positions, balances, account_meta = map_devconsole_account_update(account_update_payload)
    await writer.write_account_update(account_meta=account_meta, positions=positions, balances=balances)
    print("  Upserted sample positions and balances.")

    print("Stream Bridge local test harness finished successfully.")

if __name__ == "__main__":
    # If no project is configured locally, default to DRY_RUN.
    if not (os.getenv("FIRESTORE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")):
        os.environ["DRY_RUN"] = "1"
    asyncio.run(main())
