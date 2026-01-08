from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from backend.common.kill_switch import get_kill_switch_state

TRUTHY = {"1", "true", "yes", "on", "y", "t"}
FALSY = {"0", "false", "no", "off", "n", "f"}

# Operator-facing ingest switch (separate from global kill switch).
INGEST_ENABLED_ENV = "INGEST_ENABLED"
INGEST_ENABLED_FILE_ENV = "INGEST_ENABLED_FILE"


def _parse_bool(value: object | None) -> Optional[bool]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    return None


def _read_first_line(path: str) -> str:
    # Keep it tiny and safe: read only the first line.
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return (data.splitlines()[0] if data else "").strip()


def get_ingest_enabled_state(*, default_enabled: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Returns (enabled, source) for the ingestion switch *only* (not the global kill switch).

    Sources:
    - "env:INGEST_ENABLED"
    - "file:<path>" (from INGEST_ENABLED_FILE)
    """
    env_v = _parse_bool(os.getenv(INGEST_ENABLED_ENV))
    if env_v is not None:
        return bool(env_v), f"env:{INGEST_ENABLED_ENV}"

    file_path = (os.getenv(INGEST_ENABLED_FILE_ENV) or "").strip()
    if file_path:
        try:
            file_v = _parse_bool(_read_first_line(file_path))
            if file_v is not None:
                return bool(file_v), f"file:{file_path}"
        except Exception:
            # Fail-open for the ingest-only switch on unreadable file.
            return bool(default_enabled), None

    return bool(default_enabled), None


def get_effective_ingest_enabled_state(*, default_enabled: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Returns (enabled, source) where the global kill switch always forces ingestion disabled.
    """
    kill, kill_source = get_kill_switch_state()
    if kill:
        return False, f"kill_switch:{kill_source or 'enabled'}"

    enabled, src = get_ingest_enabled_state(default_enabled=default_enabled)
    if not enabled:
        return False, src or f"env:{INGEST_ENABLED_ENV}"
    return True, src

