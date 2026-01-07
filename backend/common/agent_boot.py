import os
import json
import logging
from datetime import datetime, timezone


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else default


def configure_startup_logging(agent_name: str, intent: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent_name": agent_name,
        "intent": intent,
        "git_sha": _env("GIT_SHA", "unknown"),
        "agent_mode": _env("AGENT_MODE", "DISABLED"),
        "env": _env("ENVIRONMENT", "prod"),
    }
    logging.info(json.dumps(payload))


def require_live_mode() -> None:
    mode = _env("AGENT_MODE", "DISABLED").upper()
    if mode != "LIVE":
        raise RuntimeError(
            f"Trading is disabled. Set AGENT_MODE=LIVE to enable. Current={mode}"
        )


def marketdata_is_stale(max_age_seconds: int = 30) -> bool:
    # Placeholder: wire to your real heartbeat later.
    # If you have a heartbeat timestamp env var or file, read it here.
    ts = _env("MARKETDATA_HEARTBEAT_EPOCH", "")
    if not ts:
        return True
    try:
        age = int(datetime.now(timezone.utc).timestamp()) - int(ts)
        return age > max_age_seconds
    except Exception:
        return True

