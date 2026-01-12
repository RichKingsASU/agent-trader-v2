import asyncio
from .driver import run_strategy
import logging
from backend.common.logging import init_structured_logging

init_structured_logging(service="strategy-engine-local-test")
logger = logging.getLogger(__name__)

async def main():
    """
    Runs the strategy engine in dry-run mode for local testing.
    """
    logger.info("Running Strategy Engine in Dry-Run Mode", extra={"event_type": "local_test.start"})
    await run_strategy(execute=False)
    logger.info("Strategy Engine Dry-Run Complete", extra={"event_type": "local_test.end"})

if __name__ == "__main__":
    # Ensure DATABASE_URL is set
    import os
    if "DATABASE_URL" not in os.environ:
        logger.error(
            "DATABASE_URL environment variable not set; please set it before running the test.",
            extra={"event_type": "config.missing", "missing": ["DATABASE_URL"]},
        )
    else:
        asyncio.run(main())