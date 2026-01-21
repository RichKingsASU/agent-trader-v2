"""
Centralized config helpers + startup env contract validation.

This module is intentionally lightweight: it must be importable in unit tests
and at service startup before any heavy dependencies are imported.

See `docs/CONFIG_SECRETS.md` and `docs/CANONICAL_ENV_VAR_CONTRACT.md`.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Mapping, Sequence

__all__ = [
    "env_str",
    "env_int",
    "env_csv",
    "validate_or_exit",
    "_parse_bool",
    "_as_int_or_none",
    "_as_float_or_none",
    "_require_env_string",
]


def _parse_bool(v: Any, default: bool = False) -> bool:
    """
    Parse common boolean env encodings.
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    s = str(v).strip().lower()
    if not s:
        return bool(default)
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    return bool(default)


def env_str(
    name: str,
    default: str | None = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """
    Read a string env var. Returns `default` if missing/blank unless `required=True`.
    """
    env_map = env or os.environ
    raw = env_map.get(name)
    if raw is None:
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    s = str(raw).strip()
    if not s:
        if required:
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
    Read an int env var.
    """
    s = env_str(name, default=None, required=required, env=env)
    if s is None:
        return default
    try:
        return int(str(s).strip())
    except Exception:
        raise RuntimeError(f"Invalid int env var {name}={s!r}")


def env_csv(
    name: str,
    default: Sequence[str] | None = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """
    Read a comma-separated env var into a list of non-empty strings.
    """
    s = env_str(name, default=None, required=required, env=env)
    if s is None:
        return list(default or [])
    out: list[str] = []
    for part in str(s).split(","):
        p = str(part).strip()
        if p:
            out.append(p)
    if not out and required:
        raise RuntimeError(f"Missing required env var: {name}")
    return out or list(default or [])


def _as_int_or_none(v: str | None) -> int | None:
    try:
        if v is None:
            return None
        return int(str(v).strip())
    except Exception:
        return None


def _as_float_or_none(v: str | None) -> float | None:
    try:
        if v is None:
            return None
        return float(str(v).strip())
    except Exception:
        return None


def _require_env_string(name: str, default: str | None = None, *, env: Mapping[str, str] | None = None) -> str:
    v = env_str(name, default=default, required=(default is None), env=env)
    if v is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v)


# --- Fail-fast startup contract validation ---

# For keys that are "one-of" groups, represent them as a single required token.
_ALT_MARKETDATA_URL = "MARKETDATA_HEALTH_URL|MARKETDATA_HEARTBEAT_URL"

REQUIRED_BY_SERVICE: dict[str, tuple[str, ...]] = {
    # Cloud Run ingestion job/service.
    "cloudrun-ingestor": (
        "GCP_PROJECT",
        "SYSTEM_EVENTS_TOPIC",
        "MARKET_TICKS_TOPIC",
        "MARKET_BARS_1M_TOPIC",
        "TRADE_SIGNALS_TOPIC",
        "INGEST_FLAG_SECRET_ID",
    ),
    # Cloud Run consumer (Pub/Sub push -> Firestore).
    "cloudrun-consumer": (
        "GCP_PROJECT",
        "SYSTEM_EVENTS_TOPIC",
        "INGEST_FLAG_SECRET_ID",
    ),
    # Strategy engine service (health endpoints + evaluation loop).
    "strategy-engine": (
        _ALT_MARKETDATA_URL,
    ),
    # Stream bridge (external streams -> Firestore).
    "stream-bridge": (
        # Firestore project id can come from either var.
        "FIRESTORE_PROJECT_ID|GOOGLE_CLOUD_PROJECT",
    ),
}


def _missing_for_service(service: str, env_map: Mapping[str, str]) -> list[str]:
    required = REQUIRED_BY_SERVICE.get(service, ())
    missing: list[str] = []
    for token in required:
        if "|" not in token:
            if not env_str(token, default=None, required=False, env=env_map):
                missing.append(token)
            continue
        # one-of group
        opts = [p.strip() for p in token.split("|") if p.strip()]
        if not any(env_str(o, default=None, required=False, env=env_map) for o in opts):
            missing.append(token)
    return missing


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Fail-fast validation used by container entrypoints.

    Output is a single line so ops tooling can parse it:
    `CONFIG_FAIL service=<svc> missing=K1,K2 action="..."`
    """
    env_map = env or os.environ
    missing = _missing_for_service(service, env_map)
    if not missing:
        return

    msg = (
        f'CONFIG_FAIL service={service} missing={",".join(missing)} '
        'action="Set missing env vars (Cloud Run: --set-env-vars/--set-secrets). '
        'See docs/CONFIG_SECRETS.md"'
    )
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    raise SystemExit(2)

