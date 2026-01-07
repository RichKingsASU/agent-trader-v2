"""
Universal agent identity + intent logging (v2).

Back-compat wrapper used by multiple services; delegates to the institutional
`backend.observability.*` modules.
"""

from __future__ import annotations

import platform
from typing import Any, Optional

from backend.common.audit_logging import configure_audit_log_enrichment
from backend.observability.logger import log_event, log_agent_start_banner
from backend.observability.agent_identity import require_identity_env, get_runtime_metadata


def configure_startup_logging(agent_name: str, intent: str) -> None:
    """
    Emit a startup "identity banner" intent log.

    Notes:
    - Identity is sourced from env vars (REPO_ID/AGENT_NAME/AGENT_ROLE/AGENT_MODE).
    - This function will fail fast if identity env vars are missing/invalid.
    - `agent_name` argument is retained only for back-compat; mismatches are logged.
    """
    ident = require_identity_env()
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
    # Ensure standard python logging (when used) has audit enrichment fields available.
    configure_audit_log_enrichment(agent_name=ident.get("agent_name") or agent_name or None)
    log_agent_start_banner(summary=intent, extra=extra)

