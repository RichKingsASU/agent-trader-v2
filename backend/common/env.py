"""
Environment variable helpers.

SAFE CLEANUP NOTE:
- Must remain dependency-light and safe to import during test collection.
- Must not perform network I/O at import time.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from urllib.parse import urlparse

from backend.common.secrets import get_secret

_allow_env_fallback: Optional[bool] = None


def _should_allow_env_fallback() -> bool:
    """
    Global policy: allow falling back to process env vars when Secret Manager
    isn't available.

    Enabled by `ALLOW_ENV_SECRET_FALLBACK=1`.
    """
    global _allow_env_fallback
    if _allow_env_fallback is None:
        _allow_env_fallback = os.getenv("ALLOW_ENV_SECRET_FALLBACK", "0").strip().lower() == "1"
    return _allow_env_fallback


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    """
    Read a runtime configuration value.

    Order:
    - Secret Manager via `get_secret` (best-effort; call-time only).
    - Environment variable (only if ALLOW_ENV_SECRET_FALLBACK=1).
    - `default`
    """
    try:
        value = get_secret(name, fail_if_missing=False)
    except Exception:
        value = ""

    if value is not None and str(value).strip() != "":
        return str(value).strip()

    if _should_allow_env_fallback():
        env_value = os.getenv(name)
        if env_value is not None and str(env_value).strip() != "":
            return str(env_value).strip()

    if required:
        raise RuntimeError(f"Missing required env var or secret: {name}")

    return default


def get_firebase_project_id(*, required: bool = False) -> str:
    """
    Preferred:
    - FIREBASE_PROJECT_ID

    Acceptable fallbacks:
    - FIRESTORE_PROJECT_ID
    - GOOGLE_CLOUD_PROJECT
    - GCP_PROJECT
    """
    v = (
        get_env("FIREBASE_PROJECT_ID", default=None)
        or get_env("FIRESTORE_PROJECT_ID", default=None)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None)
        or get_env("GCP_PROJECT", default=None)
    )
    if v:
        return str(v).strip()
    if required:
        raise RuntimeError(
            "Missing required env var: FIREBASE_PROJECT_ID (or FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT / GCP_PROJECT)"
        )
    return ""


def get_vertex_ai_model_id(*, default: str = "gemini-2.5-flash") -> str:
    return str(get_env("VERTEX_AI_MODEL_ID", default=default) or default)


def get_vertex_ai_project_id(*, required: bool = False) -> str:
    v = get_env("VERTEX_AI_PROJECT_ID", default=None) or get_firebase_project_id(required=required)
    return str(v or "")


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    return str(get_env("VERTEX_AI_LOCATION", default=default) or default)


def get_alpaca_key_id(*, required: bool = True) -> Optional[str]:
    v = get_env("APCA_API_KEY_ID", default=None, required=required)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def get_alpaca_api_key(*, required: bool = True) -> Optional[str]:
    # Alias used by some modules.
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str | None:
    """
    Env contract (official Alpaca SDK):
    - APCA_API_SECRET_KEY
    """
    v = get_env("APCA_API_SECRET_KEY", None, required=required)
    if v is not None and str(v).strip():
        return str(v).strip()
    # Common aliases (best-effort).
    for alias in ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY", "APCA_API_SECRET"):
        a = get_env(alias, None, required=False)
        if a is not None and str(a).strip():
            s = str(a).strip()
            os.environ.setdefault("APCA_API_SECRET_KEY", s)
            return s
    return None


def get_alpaca_api_base_url(*, required: bool = True) -> str | None:
    """
    Returns the Alpaca trading API base URL.

    Official Alpaca SDK env var:
    - APCA_API_BASE_URL
    """
    # Safe to read, and some runtimes gate behavior on its presence.
    _ = os.getenv("ALPACA_ENV")

    v = get_env("APCA_API_BASE_URL", default=None, required=False)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError("Missing required env var: APCA_API_BASE_URL")
        return None
    s = str(v).strip()
    return s[:-1] if s.endswith("/") else s


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Hard safety check: in paper mode, only the paper Alpaca host is allowed.
    """
    raw = str(url or "").strip()
    if not raw:
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")
    # Disallow any explicit port, even 443 (defense-in-depth).
    if parsed.port is not None:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    host = (parsed.hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: paper trading requires https://paper-api.alpaca.markets (got {raw!r})")
    # Strict: exact base URL only (no path, no trailing slash).
    if raw != "https://paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: paper trading requires https://paper-api.alpaca.markets (got {raw!r})")
    return raw


def assert_valid_alpaca_base_url(url: str, agent_mode: str, trading_mode: str) -> str:
    """
    Conservative validation helper used by scripts/tests.
    """
    _ = agent_mode
    raw = str(url or "").strip()
    if not raw:
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")

    host = (parsed.hostname or "").lower()
    if str(trading_mode).lower() == "paper":
        if host != "paper-api.alpaca.markets":
            raise RuntimeError(
                f"REFUSED: TRADING_MODE='paper' requires Alpaca base URL to be 'https://paper-api.alpaca.markets'. Got: {raw!r}"
            )
        return raw[:-1] if raw.endswith("/") else raw

    # In non-paper modes, we don't enforce here; higher-level guards handle live-vs-disabled.
    return raw[:-1] if raw.endswith("/") else raw


__all__ = [
    "get_env",
    "get_firebase_project_id",
    "get_vertex_ai_model_id",
    "get_vertex_ai_project_id",
    "get_vertex_ai_location",
    "get_alpaca_key_id",
    "get_alpaca_api_key",
    "get_alpaca_secret_key",
    "get_alpaca_api_base_url",
    "assert_paper_alpaca_base_url",
    "assert_valid_alpaca_base_url",
]

