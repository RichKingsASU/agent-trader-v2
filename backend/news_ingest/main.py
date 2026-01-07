from __future__ import annotations

# Fail-fast runtime guard (forbid EXECUTE, require valid AGENT_MODE).
from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import json
import logging
import os
import sys

from backend.common.runtime_fingerprint import log_runtime_fingerprint
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.safety.startup_validation import validate_agent_mode_or_exit

from .config import from_env
from .news_api import StubNewsApiClient
from .service import NewsIngestor

logger = logging.getLogger(__name__)


def main() -> None:
    # Basic logging (service is intended to run as a simple process / container).
    level = (os.getenv("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Enforce OBSERVE-only at runtime for this service.
    validate_agent_mode_or_exit(allowed={"OBSERVE"})

    # Log runtime fingerprint + build fingerprint (best-effort).
    log_runtime_fingerprint(service="news-ingest")
    try:
        fp = get_build_fingerprint()
        print(json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False), flush=True)
    except Exception:
        pass

    cfg = from_env()
    client = StubNewsApiClient(source=cfg.source)
    ingestor = NewsIngestor(cfg=cfg, client=client)

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

