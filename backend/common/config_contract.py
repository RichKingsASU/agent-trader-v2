"""
Config Validation + Required Env Contract

Goal:
Fail fast at startup with clear, single-line errors (avoid crash loops mid-import).

Usage (place at top of entrypoint modules, before other backend imports):

    from backend.common.config_contract import validate_or_exit as _validate_or_exit
    _validate_or_exit("marketdata-mcp-server")
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

# A requirement can be either:
# - "ENV_VAR_NAME" (must be present and non-empty)
# - ("ENV_A", "ENV_B", ...) (at least one must be present and non-empty)
EnvRequirement = str | Sequence[str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(env: Mapping[str, str], name: str) -> str | None:
    v = env.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


def _format_requirement(req: EnvRequirement) -> str:
    if isinstance(req, str):
        return req
    # Accept list/tuple/etc; render as "A|B|C" to denote "any of"
    parts = [str(x).strip() for x in req if str(x).strip()]
    return "|".join(parts) if parts else "<invalid>"


# Required env var contract per service.
#
# Keep this list minimal and focused on vars that would otherwise crash the
# process during import or immediately at runtime.
REQUIRED_ENV_BY_SERVICE: dict[str, list[EnvRequirement]] = {
    # Serves marketdata MCP endpoints and runs Alpaca streamer background task.
    "marketdata-mcp-server": [
        # Alpaca credentials (official Alpaca SDK env names).
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "APCA_API_BASE_URL",
        # Streamer persistence target.
        "DATABASE_URL",
    ],
    # Strategy-engine service (FastAPI + periodic strategy evaluation loop).
    "strategy-engine": [
        # Strategy reads from DB (bars/options flow) and logs decisions.
        "DATABASE_URL",
        # Required for safe-by-default stale-marketdata gating. Support legacy/manifest name.
        ("MARKETDATA_HEALTH_URL", "MARKETDATA_HEARTBEAT_URL"),
    ],
}


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Validate env var contract for the given service.

    On failure:
    - prints a single line that begins with "CONTRACT_FAIL"
    - exits with code 1
    """
    e: Mapping[str, str] = env or os.environ  # type: ignore[assignment]
    key = (service or "").strip()
    required = REQUIRED_ENV_BY_SERVICE.get(key, [])
    if not required:
        # Unknown service => no required env contract enforced here.
        return

    missing: list[str] = []
    for req in required:
        if isinstance(req, str):
            if _get(e, req) is None:
                missing.append(req)
            continue

        # Any-of group.
        group = [str(x).strip() for x in req if str(x).strip()]
        if not group:
            missing.append("<invalid>")
            continue
        if all(_get(e, n) is None for n in group):
            missing.append(_format_requirement(group))

    if not missing:
        return

    payload = {
        "ts": _utc_now_iso(),
        "service": key,
        "missing": missing,
        "required": [_format_requirement(r) for r in required],
    }
    try:
        # Single-line log for container collectors.
        print("CONTRACT_FAIL " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)
    except Exception:
        pass
    raise SystemExit(1)

