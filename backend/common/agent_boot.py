"""
Universal agent identity + intent logging (ops-friendly).

Back-compat wrapper used by multiple services; delegates to:
- `backend.observability.agent_identity`
- `backend.observability.logger`
"""

from __future__ import annotations

import platform
from typing import Any, Optional

from backend.common.audit_logging import configure_audit_log_enrichment, set_correlation_id
from backend.observability.agent_identity import get_runtime_metadata, require_identity_env
from backend.observability.logger import log_agent_start_banner, log_event


def _safe_platform() -> str:
    try:
        return platform.platform()
    except Exception:
        return "unknown"


def configure_startup_logging(agent_name: str, intent: str) -> None:
    """
    Emit a startup identity banner as a single JSON line.

    This fails fast if the institutional identity env vars are missing.
    """
    ident = require_identity_env()

    # Enrich non-JSON python logging (best-effort).
    try:
        set_correlation_id("startup")
        configure_audit_log_enrichment(agent_name=ident.get("agent_name"))
    except Exception:
        pass

    if agent_name and ident.get("agent_name") and agent_name != ident["agent_name"]:
        log_event(
            "agent_identity_mismatch",
            level="WARNING",
            expected_agent_name=ident["agent_name"],
            configured_agent_name=agent_name,
        )

    extra: dict[str, Any] = {
        "agent_version": ident.get("agent_version"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "runtime": get_runtime_metadata(),
    }

    # Uses `backend.observability.logger` (now includes severity/service/image_tag).
    log_agent_start_banner(summary=intent, extra=extra)

