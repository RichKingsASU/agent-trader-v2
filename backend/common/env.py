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

    Preferred:
    - FIREBASE_PROJECT_ID

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
        raise RuntimeError(
            "Missing required env var: FIREBASE_PROJECT_ID (or FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT)"
        )
    return ""


def get_vertex_ai_model_id(*, default: str = "gemini-2.5-flash") -> str:
    """
    Resolve the Vertex AI model id used for Gemini.
    """
    return str(get_env("VERTEX_AI_MODEL_ID", default=default, required=False))

def get_env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default

def get_vertex_ai_project_id(*, required: bool = False) -> str:
    """
    Resolve the Vertex AI project id.

    Priority:
    - VERTEX_AI_PROJECT_ID (explicit override)
    - FIREBASE_PROJECT_ID (repo standard)
    - GOOGLE_CLOUD_PROJECT (ADC default)
    """
    v = (
        get_env("VERTEX_AI_PROJECT_ID", default=None, required=False)
        or get_env("FIREBASE_PROJECT_ID", default=None, required=False)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None, required=False)
    )
    if v:
        return str(v)
    if required:
        raise RuntimeError(
            "Missing required env var: VERTEX_AI_PROJECT_ID (or FIREBASE_PROJECT_ID / GOOGLE_CLOUD_PROJECT)"
        )
    return ""


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    """
    Resolve the Vertex AI location/region.
    """
    return str(get_env("VERTEX_AI_LOCATION", default=default, required=False))

# --- Alpaca (paper-only safety boundary) ---

def get_alpaca_key_id(*, required: bool = True) -> str:
    """
    Returns the Alpaca API key id.

    Env contract (official Alpaca SDK):
    - APCA_API_KEY_ID
    """
    # Canonical (official Alpaca SDK)
    v = get_env("APCA_API_KEY_ID", default=None, required=False)
    # Common historical/infra aliases (normalize to canonical so Alpaca SDKs can read them).
    v = v or get_env("ALPACA_API_KEY", default=None, required=False)
    v = v or get_env("ALPACA_API_KEY_ID", default=None, required=False)
    v = v or get_env("APCA_API_KEY", default=None, required=False)  # legacy
    if v:
        s = str(v).strip()
        if s:
            # Ensure canonical env var is present for downstream libs (alpaca-py / alpaca-trade-api).
            os.environ.setdefault("APCA_API_KEY_ID", s)
            return s

    if required:
        raise RuntimeError("Missing required env var: APCA_API_KEY_ID")
    return ""


def get_alpaca_api_key(*, required: bool = True) -> str:
    """
    Alias for get_alpaca_key_id(), for clarity in new code.
    """
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str:
    """
    Returns the Alpaca API secret key.

    Env contract (official Alpaca SDK):
    - APCA_API_SECRET_KEY
    """
    # Canonical (official Alpaca SDK)
    v = get_env("APCA_API_SECRET_KEY", default=None, required=False)
    # Common historical/infra aliases (normalize to canonical so Alpaca SDKs can read them).
    v = v or get_env("ALPACA_SECRET_KEY", default=None, required=False)
    v = v or get_env("ALPACA_API_SECRET_KEY", default=None, required=False)
    v = v or get_env("APCA_API_SECRET", default=None, required=False)  # legacy
    if v:
        s = str(v).strip()
        if s:
            os.environ.setdefault("APCA_API_SECRET_KEY", s)
            return s

    if required:
        raise RuntimeError("Missing required env var: APCA_API_SECRET_KEY")
    return ""


def get_alpaca_api_base_url(*, required: bool = True) -> str:
    """
    Returns the Alpaca API base URL.

    Env contract (official Alpaca SDK):
    - APCA_API_BASE_URL
    """
    # Canonical (official Alpaca SDK)
    v = get_env("APCA_API_BASE_URL", default=None, required=False)
    # Common historical/infra aliases.
    v = v or get_env("ALPACA_TRADING_HOST", default=None, required=False)
    v = v or get_env("ALPACA_API_BASE_URL", default=None, required=False)
    v = v or get_env("ALPACA_API_URL", default=None, required=False)
    if v:
        s = str(v).strip()
        s = s[:-1] if s.endswith("/") else s
        if s:
            os.environ.setdefault("APCA_API_BASE_URL", s)
            return assert_paper_alpaca_base_url(s)
    if required:
        raise RuntimeError("Missing required env var: APCA_API_BASE_URL")
    return ""


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Absolute safety boundary: allow ONLY Alpaca paper trading API base URLs.

    Allowed:
    - https://paper-api.alpaca.markets
    - https://paper-api.alpaca.markets/<path> (some callers store /v2, etc.)

    Forbidden (hard fail):
    - anything containing "api.alpaca.markets" that is NOT the paper host
    - any scheme other than https
    - any host other than paper-api.alpaca.markets
    """
    if url is None or str(url).strip() == "":
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

def get_alpaca_api_key(*, required: bool = False) -> str:
    # Back-compat name used in some modules.
    return get_alpaca_key_id(required=required)

    # Explicit hard-fail: never allow live trading host.
    if "api.alpaca.markets" in lowered and "paper-api.alpaca.markets" not in lowered:
        raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden: {raw!r}")

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    if (parsed.hostname or "").lower() != "paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be paper host: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"Alpaca base URL must not include query/fragment: {raw!r}")

