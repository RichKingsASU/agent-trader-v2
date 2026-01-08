from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}

# Preferred ingest enable flag.
INGEST_ENABLED_ENV = "INGEST_ENABLED"

# Optional: point to a file whose contents are truthy/falsey.
# Useful for Kubernetes ConfigMap mounts or secret volumes.
INGEST_ENABLED_FILE_ENV = "INGEST_ENABLED_FILE"


def _normalize(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _read_first_line(path: str) -> str:
    # Keep it tiny and safe: read only a small prefix.
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return (data.splitlines()[0] if data else "").strip()


def get_ingest_enabled_state() -> Tuple[bool, Optional[str]]:
    """
    Returns (enabled, source).

    Semantics:
    - Default is enabled (fail-open) if no flag is provided.
    - If INGEST_ENABLED is explicitly set to a falsy value, ingestion is disabled.
    - If INGEST_ENABLED_FILE is set and the file contains a falsy value, ingestion is disabled.

    Source values:
    - "env:INGEST_ENABLED"
    - "file:<path>" (from INGEST_ENABLED_FILE)
    """
    env_v = os.getenv(INGEST_ENABLED_ENV)
    if env_v is not None:
        v = _normalize(env_v)
        if v in TRUTHY:
            return True, f"env:{INGEST_ENABLED_ENV}"
        if v in FALSY:
            return False, f"env:{INGEST_ENABLED_ENV}"
        # Unknown value => fail-open but still record the source for visibility.
        return True, f"env:{INGEST_ENABLED_ENV}"

    file_path = (os.getenv(INGEST_ENABLED_FILE_ENV) or "").strip()
    if file_path:
        try:
            v = _normalize(_read_first_line(file_path))
            if v in TRUTHY:
                return True, f"file:{file_path}"
            if v in FALSY:
                return False, f"file:{file_path}"
            return True, f"file:{file_path}"
        except Exception:
            # Fail-open: unreadable file should not halt ingestion unexpectedly.
            return True, None

    return True, None


def is_ingest_enabled() -> bool:
    enabled, _ = get_ingest_enabled_state()
    return enabled

