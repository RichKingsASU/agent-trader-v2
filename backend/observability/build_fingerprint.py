"""
Build fingerprint (deterministic container self-identity).

This module is intentionally dependency-free and safe to import in all services.
"""

from __future__ import annotations

import os
from typing import Any, Dict


_REPO_ID = "agent-trader-v2"


def _env(name: str) -> str:
    v = os.getenv(name)
    if v is None:
        return "unknown"
    s = str(v).strip()
    return s if s else "unknown"


def get_build_fingerprint() -> Dict[str, Any]:
    """
    Return a small, stable identity payload for auditing and ops correlation.

    Fields are populated from environment variables when available.
    """
    return {
        "repo_id": _REPO_ID,
        "git_sha": _env("GIT_SHA"),
        "build_id": _env("BUILD_ID"),
        "image_ref": _env("IMAGE_REF"),
        "build_time_utc": _env("BUILD_TIME_UTC"),
    }

