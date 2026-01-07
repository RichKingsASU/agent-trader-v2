from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="stream-bridge")

import asyncio
import json
import logging
import os
import signal
from .config import load_config
from .firestore_writer import FirestoreWriter
from .streams.price_stream_client import PriceStreamClient
from .streams.options_flow_client import OptionsFlowClient
from .streams.news_stream_client import NewsStreamClient
from .streams.account_updates_client import AccountUpdatesClient

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.observability.ops_json_logger import OpsLogger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="stream-bridge",
        intent="Bridge upstream streams into Firestore (price, options flow, news, account updates).",
    )
    ops = OpsLogger("stream-bridge")
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
    heartbeat_task = asyncio.create_task(_heartbeat_loop(ops))
    try:
        ops.readiness(ready=True)
    except Exception:
        pass

    try:
        loop = asyncio.get_running_loop()

        def _initiate_shutdown() -> None:
            try:
                ops.shutdown(phase="initiated")
            except Exception:
                pass
            for t in [heartbeat_task, *tasks]:
                try:
                    t.cancel()
                except Exception:
                    pass

        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, _initiate_shutdown)
            except NotImplementedError:
                signal.signal(s, lambda *_args: _initiate_shutdown())

        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in [heartbeat_task, *tasks]:
            if t.done():
                continue
            try:
                t.cancel()
            except Exception:
                pass
        await asyncio.gather(heartbeat_task, *tasks, return_exceptions=True)
        logger.info("Stream Bridge service stopped.")

async def _heartbeat_loop(ops: OpsLogger) -> None:
    interval = float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S") or "60")
    interval = max(5.0, interval)
    while True:
        try:
            ops.heartbeat(kind="loop")
        except Exception:
            pass
        await asyncio.sleep(interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass