from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="stream-bridge")
del _log_runtime_fingerprint

import asyncio
import json
import logging
from .config import load_config
from .firestore_writer import FirestoreWriter
from .streams.price_stream_client import PriceStreamClient
from .streams.options_flow_client import OptionsFlowClient
from .streams.news_stream_client import NewsStreamClient
from .streams.account_updates_client import AccountUpdatesClient

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    configure_startup_logging(
        agent_name="stream-bridge",
        intent="Bridge upstream streams into Firestore (price, options flow, news, account updates).",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass
    logger.info("Starting Stream Bridge service...")
    cfg = load_config()
    writer = await FirestoreWriter.create_from_env()

    tasks = [
        asyncio.create_task(PriceStreamClient(cfg, writer).run_forever()),
        asyncio.create_task(OptionsFlowClient(cfg, writer).run_forever()),
        asyncio.create_task(NewsStreamClient(cfg, writer).run_forever()),
        asyncio.create_task(AccountUpdatesClient(cfg, writer).run_forever()),
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Stream Bridge service stopping.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass