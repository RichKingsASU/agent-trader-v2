from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="stream-bridge")

from backend.common.logging import init_structured_logging

init_structured_logging(service="stream-bridge")

import asyncio
import json
import logging
import os
from .config import load_config
from .firestore_writer import FirestoreWriter
from .streams.price_stream_client import PriceStreamClient
from .streams.options_flow_client import OptionsFlowClient
from .streams.news_stream_client import NewsStreamClient
from .streams.account_updates_client import AccountUpdatesClient

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.ops_metrics import REGISTRY
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.observability.ops_json_logger import OpsLogger
from backend.safety.process_safety import AsyncShutdown, startup_banner

logger = logging.getLogger(__name__)

async def main():
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="stream-bridge",
        intent="Bridge upstream streams into Firestore (price, options flow, news, account updates).",
    )
    startup_banner(
        service="stream-bridge",
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
        shutdown = AsyncShutdown(service="stream-bridge")
        shutdown.install()

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

        shutdown.add_callback(_initiate_shutdown)

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
        try:
            writer.close()
        except Exception:
            pass
        logger.info("Stream Bridge service stopped.")

async def _heartbeat_loop(ops: OpsLogger) -> None:
    interval = float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S") or "60")
    interval = max(5.0, interval)
    while True:
        try:
            # Include a small, log-friendly snapshot of in-process counters so
            # operators can see traffic without an external metrics system.
            snap = REGISTRY.snapshot()

            def _by_stream(metric_name: str) -> dict[str, int]:
                out: dict[str, float] = {}
                for label_tup, v in (snap.get(metric_name) or {}).items():
                    labels = dict(label_tup)
                    if labels.get("component") != "stream-bridge":
                        continue
                    stream = str(labels.get("stream") or "unknown")
                    out[stream] = float(out.get(stream, 0.0)) + float(v)
                # Render as ints for readability (these are counters).
                return {k: int(v) for k, v in sorted(out.items())}

            ops.heartbeat(
                kind="loop",
                messages_received_total=_by_stream("messages_received_total"),
                messages_published_total=_by_stream("messages_published_total"),
                reconnect_attempts_total=_by_stream("reconnect_attempts_total"),
            )
        except Exception:
            pass
        await asyncio.sleep(interval)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass