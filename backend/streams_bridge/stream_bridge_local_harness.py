import asyncio
import os
import json
from datetime import datetime, timezone
import logging
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import (
    map_devconsole_news,
    map_devconsole_options_flow,
    map_devconsole_account_update
)

from backend.common.logging import init_structured_logging

init_structured_logging(service="streams-bridge-local-test")
logger = logging.getLogger(__name__)

async def main():
    """
    Local smoke test for the Stream Bridge: loads fixtures, maps them, and writes to Firestore.
    """
    logger.info("Running Stream Bridge local test harness...", extra={"event_type": "local_test.start"})
    writer = await FirestoreWriter.create_from_env()

    # --- Test News Events ---
    logger.info("Testing news events...", extra={"event_type": "local_test.news.start"})
    with open("backend/streams_bridge/fixtures/news_sample.json", 'r') as f:
        news_payload = json.load(f)
    news_event = map_devconsole_news(news_payload)
    await writer.insert_news_events([news_event])
    logger.info("Inserted 1 sample news event.", extra={"event_type": "local_test.news.ok", "inserted": 1})

    # --- Test Options Flow ---
    logger.info("Testing options flow...", extra={"event_type": "local_test.options_flow.start"})
    with open("backend/streams_bridge/fixtures/options_flow_sample.json", 'r') as f:
        options_flow_payload = json.load(f)
    options_flow_event = map_devconsole_options_flow(options_flow_payload)
    await writer.insert_options_flow([options_flow_event])
    logger.info("Inserted 1 sample options flow event.", extra={"event_type": "local_test.options_flow.ok", "inserted": 1})

    # --- Test Account Updates ---
    logger.info("Testing account updates...", extra={"event_type": "local_test.account_update.start"})
    with open("backend/streams_bridge/fixtures/account_update_sample.json", 'r') as f:
        account_update_payload = json.load(f)
    positions, balances, account_meta = map_devconsole_account_update(account_update_payload)
    await writer.write_account_update(account_meta=account_meta, positions=positions, balances=balances)
    logger.info("Upserted sample positions and balances.", extra={"event_type": "local_test.account_update.ok"})

    logger.info("Stream Bridge local test harness finished successfully.", extra={"event_type": "local_test.end"})

if __name__ == "__main__":
    # If no project is configured locally, default to DRY_RUN.
    if not (os.getenv("FIRESTORE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")):
        os.environ["DRY_RUN"] = "1"
    asyncio.run(main())
