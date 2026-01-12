import asyncio
import os
from datetime import datetime, timezone
import logging
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.common.logging import init_structured_logging

init_structured_logging(service="streams-bridge-writer-smoke")
logger = logging.getLogger(__name__)

async def main():
    """Smoke test for the FirestoreWriter."""
    logger.info("Running FirestoreWriter smoke test...", extra={"event_type": "smoke_test.start"})
    writer = await FirestoreWriter.create_from_env()

    test_event = {
        "event_ts": datetime.now(timezone.utc),
        "source": "dev_console_test",
        "symbol": "SPY",
        "headline": "Stream Bridge smoke test headline",
        "body": "This is only a local smoke test.",
        "url": None,
        "category": "test",
        "sentiment": "neutral",
        "importance": 1,
        "raw": {"example": True}
    }

    try:
        await writer.insert_news_events([test_event])
        logger.info(
            "Smoke test successful: inserted 1 news event.",
            extra={"event_type": "smoke_test.ok", "inserted": 1, "kind": "news_event"},
        )
    except Exception as e:
        # Fail non-zero so Cloud Run Jobs / Scheduler can alert/retry.
        raise RuntimeError(f"Smoke test failed: {e}") from e

if __name__ == "__main__":
    # If no project is configured locally, default to DRY_RUN.
    if not (os.getenv("FIRESTORE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")):
        os.environ["DRY_RUN"] = "1"
    try:
        asyncio.run(main())
    except Exception as e:
        raise SystemExit(1) from e
