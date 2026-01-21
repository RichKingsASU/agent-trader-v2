"""
Central configuration helpers.

This module is intentionally importable in isolation and MUST NOT import runtime
logic (execution, agents, guards, brokers). It provides lightweight environment
parsers and a fail-fast env contract check used by early service entrypoints.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Mapping, Optional, Sequence

TRUTHY = {"1", "true", "t", "yes", "y", "on"}
FALSY = {"0", "false", "f", "no", "n", "off"}


def _parse_bool(value: object | None) -> Optional[bool]:
    """
    Parse a loosely-typed boolean value.

    Returns:
    - True / False for recognized values
    - None for None/empty/unknown
    """
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


def _as_int_or_none(v: str | None) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def _as_float_or_none(v: str | None) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _parse_bool_env(name: str, default: bool = False) -> bool:
    """
    Parse a boolean from environment variable `name`, defaulting if missing/invalid.
    """
    v = _parse_bool(os.getenv(name))
    return bool(v) if v is not None else bool(default)


def _require_env_string(name: str, default: Optional[str] = None) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        if default is not None:
            return default
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def env_str(
    name: str,
    default: str | None = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """
    Read a string from environment (or provided `env` mapping).
    """
    src = env if env is not None else os.environ
    raw = src.get(name)
    if raw is None:
        if required and default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    s = str(raw).strip()
    if not s:
        if required and default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return s


def env_int(
    name: str,
    default: int | None = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """
    Read an int from environment (or provided `env` mapping).
    """
    v = env_str(name, default=None, required=required and default is None, env=env)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        # Preserve fail-closed behavior for invalid int values when required;
        # otherwise fall back to default (or None).
        if required and default is None:
            raise
        return default


def env_csv(
    name: str,
    default: Sequence[str] | None = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str] | None:
    """
    Read a comma-separated list from environment.
    """
    v = env_str(name, default=None, required=required and default is None, env=env)
    if v is None:
        return list(default) if default is not None else None
    items = [s.strip() for s in str(v).split(",")]
    out = [s for s in items if s]
    if not out:
        if required and default is None:
            raise RuntimeError(f"Missing required env var: {name}")
        return list(default) if default is not None else None
    return out


_REQUIRED_BY_SERVICE: dict[str, tuple[str, ...]] = {
    # Cloud Run ingestion/consumer contracts (see docs/STARTUP_CONFIG_CHECKLIST.md).
    "cloudrun-ingestor": ("GCP_PROJECT", "SYSTEM_EVENTS_TOPIC", "INGEST_FLAG_SECRET_ID", "ENV"),
    "cloudrun-consumer": ("GCP_PROJECT", "SYSTEM_EVENTS_TOPIC", "INGEST_FLAG_SECRET_ID", "ENV"),
}


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Fail-fast environment contract validator.

    Behavior:
    - Logs a single JSON line describing presence-only required env vars.
    - Exits non-zero if any required env var is missing/blank.
    """
    required = _REQUIRED_BY_SERVICE.get(str(service), ())
    if not required:
        return

    src = env if env is not None else os.environ
    present = {k: bool((src.get(k) or "").strip()) for k in required}
    missing = [k for k, ok in present.items() if not ok]

    payload = {
        "event": "config.required_env",
        "service": str(service),
        "required_env": present,
        "missing_env": missing,
    }
    try:
        sys.stderr.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        sys.stderr.flush()
    except Exception:
        pass

    if missing:
        raise SystemExit(2)