from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


DEFAULT_STALE_THRESHOLD_SECONDS = 30

# When mounted as a ConfigMap volume, each key becomes a file.
DEFAULT_SAFETY_DIR = "/etc/agenttrader-safety"


def _read_text_file(path: str) -> Optional[str]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _get_config_value(key: str) -> Optional[str]:
    """
    Source order (prefer Kubernetes-native ConfigMap volume, then env):
    - /etc/agenttrader-safety/<KEY> (or $AGENTTRADER_SAFETY_DIR)
    - environment variable <KEY>
    """
    safety_dir = str(os.getenv("AGENTTRADER_SAFETY_DIR") or DEFAULT_SAFETY_DIR).strip() or DEFAULT_SAFETY_DIR
    file_val = _read_text_file(str(Path(safety_dir) / key))
    if file_val is not None and file_val != "":
        return file_val
    env_val = os.getenv(key)
    if env_val is None:
        return None
    env_val = str(env_val).strip()
    return env_val if env_val != "" else None


def load_kill_switch() -> bool:
    """
    Global kill-switch (fail-closed).

    Expected values: "true"/"false" (case-insensitive).
    SAFE DEFAULT: If missing/unparseable => True (halted).
    """
    raw = _get_config_value("KILL_SWITCH")
    if raw is None:
        return True
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return True


def load_stale_threshold_seconds() -> int:
    """
    Marketdata staleness threshold (seconds).

    SAFE DEFAULT: 30 seconds if missing/unparseable/out-of-range.
    """
    raw = _get_config_value("STALE_THRESHOLD_SECONDS")
    if raw is None:
        return int(DEFAULT_STALE_THRESHOLD_SECONDS)
    try:
        n = int(str(raw).strip())
        # Clamp to a reasonable range (avoid accidental negatives / huge values).
        if n < 1:
            return int(DEFAULT_STALE_THRESHOLD_SECONDS)
        if n > 3600:
            return 3600
        return n
    except Exception:
        return int(DEFAULT_STALE_THRESHOLD_SECONDS)

