from __future__ import annotations

# Fail-fast runtime guard (forbid EXECUTE, require valid AGENT_MODE).
from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import json
import logging
import os
import signal
import sys

from backend.common.logging import init_structured_logging
from backend.common.runtime_fingerprint import log_runtime_fingerprint
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.safety.startup_validation import validate_agent_mode_or_exit
from backend.safety.process_safety import startup_banner

from .config import from_env
from .news_api import StubNewsApiClient
from .service import NewsIngestor

logger = logging.getLogger(__name__)


def main() -> None:
    init_structured_logging(service="news-ingest")

    # Enforce OBSERVE-only at runtime for this service.
    validate_agent_mode_or_exit(allowed={"OBSERVE"})

    startup_banner(
        service="news-ingest",
        intent="Poll news API and persist raw events + cursor (OBSERVE-only).",
    )

    # Log runtime fingerprint + build fingerprint (best-effort).
    log_runtime_fingerprint(service="news-ingest")
    try:
        fp = get_build_fingerprint()
        logger.info(
            "build_fingerprint",
            extra={
                "event_type": "build_fingerprint",
                "intent_type": "build_fingerprint",
                "service": "news-ingest",
                **fp,
            },
        )
    except Exception:
        pass

    cfg = from_env()
    client = StubNewsApiClient(source=cfg.source)
    ingestor = NewsIngestor(cfg=cfg, client=client)

    def _handle_signal(signum: int, _frame=None) -> None:  # type: ignore[no-untyped-def]
        logger.warning("news_ingest.signal_received signum=%s; initiating shutdown", signum)
        ingestor.request_stop()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _handle_signal)
        except Exception:
            pass

    once = (os.getenv("NEWS_INGEST_ONCE") or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    if once:
        logger.info("news_ingest.run_mode=once")
        ingestor.poll_once()
        return

    logger.info("news_ingest.run_mode=forever")
    ingestor.run_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("news_ingest.crashed: %s", e)
        raise SystemExit(1)

