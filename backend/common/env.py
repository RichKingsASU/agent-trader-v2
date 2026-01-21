"""
Environment variable helpers.

This module must stay dependency-light and safe to import during startup.
It intentionally performs **no network I/O** and does not enable any broker
connectivity by itself.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse
from typing import Any

from backend.common.secrets import get_secret

def get_alpaca_key_id(*, required: bool = True) -> str | None:
    """
    Returns the Alpaca API key ID from Secret Manager (or env fallback as implemented by `get_secret`).

    - Secret name: APCA_API_KEY_ID
    - No secret access at import time (call-time only).
    """
    v = get_secret("APCA_API_KEY_ID", fail_if_missing=required)
    v = str(v).strip()
    if v == "":
        return None
    return v


def get_alpaca_secret_key(*, required: bool = True) -> str | None:
    """
    Returns the Alpaca API secret key from Secret Manager (or env fallback as implemented by `get_secret`).

    - Secret name: APCA_API_SECRET_KEY
    - No secret access at import time (call-time only).
    """
    v = get_secret("APCA_API_SECRET_KEY", fail_if_missing=required)
    v = str(v).strip()
    if v == "":
        return None
    return v


def get_alpaca_api_base_url(*, required: bool = True) -> str | None:
    """
    Returns the Alpaca trading API base URL from Secret Manager (or env fallback as implemented by `get_secret`).

    - Secret name: APCA_API_BASE_URL
    - Reads ALPACA_ENV only via os.getenv (no secrets involved).
    - No secret access at import time (call-time only).
    """
    _ = os.getenv("ALPACA_ENV")  # read via getenv only (required by platform rules)
    v = get_secret("APCA_API_BASE_URL", fail_if_missing=required)
    v = str(v).strip()
    if v == "":
        return None
    return v[:-1] if v.endswith("/") else v

def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Safety boundary: refuse any non-paper Alpaca trading host.

    Allowed:
    - https://paper-api.alpaca.markets (optionally with a path like /v2)

    Forbidden:
    - https://api.alpaca.markets (live trading host)
    - Any non-https URL
    - Any URL with credentials, query, fragment, or explicit non-443 port
    """
    raw = (str(url) if url is not None else "").strip()
    if raw == "":
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

    hostname = (parsed.hostname or "").lower()
    if hostname != "paper-api.alpaca.markets":
        # Keep the error message stable and explicit for downstream safeguards/tests.
        raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden in paper mode: {raw!r}")

    return raw[:-1] if raw.endswith("/") else raw


_allow_env_secret_fallback: bool | None = None


def _should_allow_env_fallback() -> bool:
    """
    Checks if environment fallback for secrets is enabled globally.

    This mirrors the behavior in `backend.common.secrets.get_secret` without importing
    any additional non-stdlib symbols.
    """
    global _allow_env_secret_fallback
    if _allow_env_secret_fallback is None:
        _allow_env_secret_fallback = os.getenv("ALLOW_ENV_SECRET_FALLBACK", "0").strip().lower() == "1"
    return _allow_env_secret_fallback


def _should_allow_env_fallback_for_name(name: str) -> bool:
    """
    Per-variable policy gate for env fallback.

    Today this is a simple global flag; keeping it as a function allows tightening
    later without changing call sites.
    """
    _ = name
    return _should_allow_env_fallback()

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
]


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    """
    Read an environment variable.

    - If set and non-empty, returns its string value.
    - If missing/empty, returns `default`.
    - If `required=True` and missing/empty, raises RuntimeError.
    """
    # Secret Manager first (call-time only).
    value = get_secret(name, fail_if_missing=False)
    if value is not None and str(value).strip() != "":
        return value

    # If not found in Secret Manager, check environment variable (only if allowed)
    if _should_allow_env_fallback_for_name(name):
        env_value = os.getenv(name)
        if env_value is not None and str(env_value).strip():
            return str(env_value).strip()

    # If still not found and required, raise error
    if required:
        raise RuntimeError(
            "Missing required env var: FIREBASE_PROJECT_ID (or FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT / GCP_PROJECT)"
        )
    return ""


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
    return str(get_env("VERTEX_AI_MODEL_ID", default=default))


def get_vertex_ai_project_id(*, required: bool = False) -> str:
    v = (
        get_env("VERTEX_AI_PROJECT_ID", default=None)
        or get_env("FIREBASE_PROJECT_ID", default=None)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None)
    )
    if v:
        return str(v)
    if required:
        raise RuntimeError(
            "Missing required env var: VERTEX_AI_PROJECT_ID (or FIREBASE_PROJECT_ID / GOOGLE_CLOUD_PROJECT)"
        )
    return ""


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    return str(get_env("VERTEX_AI_LOCATION", default=default))


# --- Alpaca (paper-only safety boundary) ---

def get_alpaca_key_id(*, required: bool = True) -> str:
    v = get_env("APCA_API_KEY_ID", default=None)
    v = v or get_env("ALPACA_API_KEY", default=None)
    v = v or get_env("ALPACA_API_KEY_ID", default=None)
    v = v or get_env("APCA_API_KEY", default=None)
    if v:
        s = str(v).strip()
        if s:
            os.environ.setdefault("APCA_API_KEY_ID", s)
            return s

def get_alpaca_key_id(*, required: bool = True) -> str | None:
    v = get_env("APCA_API_KEY_ID", None, required=required)
    return str(v).strip() if v is not None else None


def get_alpaca_api_key(*, required: bool = True) -> str | None:
    # Alias used in some modules.
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
    # Default to paper URL for safety if not explicitly set.
    v = get_env("APCA_API_BASE_URL", "https://paper-api.alpaca.markets", required=False)
    if required and (v is None or str(v).strip() == ""):
        raise RuntimeError("Missing required env var: APCA_API_BASE_URL")
    return str(v).strip()


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Hard safety check: paper trading must only use the paper Alpaca trading host.
    """
    raw = str(url).strip()
    if not raw:
        raise RuntimeError("Missing Alpaca base URL")
    parsed = urlparse(raw)

    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
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
    Conservative validation helper (paper vs live). Used by a few scripts/tests.
    """
    raw = str(url or "").strip()
    if not raw:
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    host = (parsed.hostname or "").lower()
    if trading_mode == "paper":
        if host != "paper-api.alpaca.markets":
            raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden in paper mode: {raw!r}")
    return raw[:-1] if raw.endswith("/") else raw

