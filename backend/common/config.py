"""
Runtime configuration helpers + startup contract validation.

This module is intentionally **env-only**:
- It must be safe to import very early during service startup.
- It must NOT resolve secrets (no Secret Manager calls, no secret values logged).

Secrets should be resolved via `backend.common.secrets.get_secret(...)` at runtime.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------
def _parse_bool(raw: str) -> bool:
    v = str(raw or "").strip().lower()
    return v in {"1", "true", "t", "yes", "y", "on"}


def _as_int_or_none(v: str | None) -> int | None:
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _as_float_or_none(v: str | None) -> float | None:
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _require_env_string(name: str, *, env: Mapping[str, str] | None = None) -> str:
    env_map = env if env is not None else os.environ
    v = str(env_map.get(name, "") or "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


# ---------------------------------------------------------------------------
# Env readers (non-secret config only)
# ---------------------------------------------------------------------------
def env_str(
    name: str,
    default: Optional[str] = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> Optional[str]:
    env_map = env if env is not None else os.environ
    v = env_map.get(name)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return str(v).strip()


def env_int(
    name: str,
    default: Optional[int] = None,
    *,
    required: bool = False,
    env: Mapping[str, str] | None = None,
) -> Optional[int]:
    raw = env_str(name, default=None, required=required, env=env)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        if required:
            raise RuntimeError(f"Invalid int for env var {name}: {raw!r}")
        return default


def env_csv(
    name: str,
    *,
    default: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    raw = env_str(name, default=None, required=False, env=env)
    if raw is None or str(raw).strip() == "":
        return list(default or [])
    return [s.strip() for s in str(raw).split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Startup validation (presence only; no secret values printed)
# ---------------------------------------------------------------------------
def _missing_vars(required: Iterable[str], *, env: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    for k in required:
        if not str(env.get(k, "") or "").strip():
            missing.append(k)
    return missing


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Fail-fast startup contract validation (single-line error).

    This checks presence of required env vars only. It does NOT read Secret Manager.
    """

    env_map = env if env is not None else os.environ

    # Keep these sets minimal and conservative; service code will enforce deeper rules.
    required_by_service: dict[str, list[str]] = {
        "cloudrun-ingestor": [
            "GCP_PROJECT",
            "SYSTEM_EVENTS_TOPIC",
            "MARKET_TICKS_TOPIC",
            "MARKET_BARS_1M_TOPIC",
            "TRADE_SIGNALS_TOPIC",
            "INGEST_FLAG_SECRET_ID",
        ],
        "cloudrun-consumer": [
            "GCP_PROJECT",
            "SYSTEM_EVENTS_TOPIC",
            "INGEST_FLAG_SECRET_ID",
            "PORT",
        ],
        "strategy-engine": [
            # Secret is injected into env by deploy-time secret mapping.
            "DATABASE_URL",
        ],
        "stream-bridge": [
            # Project id is required for Firestore writes.
            "FIRESTORE_PROJECT_ID",
        ],
    }

    required = required_by_service.get(service, [])
    missing = _missing_vars(required, env=env_map)
    if not missing:
        return

    msg = (
        "CONFIG_FAIL "
        f"service={service} "
        f"missing={','.join(missing)} "
        'action="Set missing env vars (Cloud Run: --set-env-vars/--set-secrets). See docs/CONFIG_SECRETS.md"'
    )
    # Single line to stderr (per docs/CONFIG_SECRETS.md).
    print(msg, file=sys.stderr)
    raise SystemExit(2)

