from __future__ import annotations

import os
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


def _get_required(name: str, default: Any = None, *, required: bool = True) -> Any:
    """
    Reads an environment variable, falling back to Secret Manager if available.
    If required and not found, raises RuntimeError.
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
        raise RuntimeError(f"Missing required secret: tried {names}")
    return ""


def get_env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


# --- Alpaca (paper-only safety boundary) ---

_ALPACA_KEY_ID_NAMES = ["APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_API_KEY"]
_ALPACA_SECRET_KEY_NAMES = ["APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY", "ALPACA_SECRET_KEY"]
_ALPACA_BASE_URL_NAMES = ["APCA_API_BASE_URL", "ALPACA_API_BASE_URL", "ALPACA_TRADING_HOST", "ALPACA_API_URL"]


def get_alpaca_key_id(*, required: bool = False) -> str:
    return _get_secret_any(_ALPACA_KEY_ID_NAMES, required=required)


def get_alpaca_api_key(*, required: bool = False) -> str:
    # Back-compat name used in some modules.
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = False) -> str:
    return _get_secret_any(_ALPACA_SECRET_KEY_NAMES, required=required)


def get_alpaca_api_base_url(*, required: bool = False) -> str | None:
    v = _get_secret_any(_ALPACA_BASE_URL_NAMES, required=required)
    return _norm_url(v) if v else None


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Hard safety boundary: only allow Alpaca PAPER trading host.

    Allowed host:
    - paper-api.alpaca.markets
    """
    raw = _norm_url(url)
    if not raw:
        raise RuntimeError("Missing Alpaca base URL")

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"Alpaca base URL must be https: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"Alpaca base URL must not include query/fragment: {raw!r}")

    host = (parsed.hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise RuntimeError(
            f"Paper trading only: expected 'https://paper-api.alpaca.markets', got {raw!r}"
        )
    return raw


def is_execution_enabled() -> bool:
    """
    Paper safety default: execution is disabled unless explicitly enabled.
    """
    raw = (os.getenv("EXECUTION_ENABLED") or "").strip().lower()
    return raw in TRUTHY


# --- Vertex AI helpers (non-trading) ---

def get_vertex_ai_project_id(*, required: bool = False) -> str:
    v = _first_nonempty(
        os.getenv("VERTEX_AI_PROJECT_ID"),
        os.getenv("FIREBASE_PROJECT_ID"),
        os.getenv("GOOGLE_CLOUD_PROJECT"),
    )
    if not v and required:
        raise RuntimeError("Missing Vertex AI project id")
    return v or ""


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    return (os.getenv("VERTEX_AI_LOCATION") or default).strip() or default


def get_vertex_ai_model_id(*, default: str = "gemini-2.5-flash") -> str:
    return (os.getenv("VERTEX_AI_MODEL_ID") or default).strip() or default

