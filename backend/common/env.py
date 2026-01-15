from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any

from backend.common.secrets import get_secret

# Define AgentMode Enum if not already defined or imported. Assuming it's available.
# If not, it might need a placeholder or import. For now, assuming it's available.
# Placeholder for AgentMode if not imported elsewhere:
# class AgentMode:
#     PAPER = "paper"
#     LIVE = "live"
#     SANDBOX = "sandbox"

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
        raise RuntimeError(f"Missing required secret or env var: {name}")
    
    # Return default if not required and not found
    return default

# Helper to determine if env fallback is allowed for a specific secret name
def _should_allow_env_fallback_for_name(name: str) -> bool:
    """
    Determines if environment variable fallback is allowed for a specific secret name.
    DATABASE_URL always forbids fallback. Other secrets may fallback if ALLOW_ENV_SECRET_FALLBACK=1.
    """
    if name == "DATABASE_URL":
        return False
    # Check global fallback setting if it's not DATABASE_URL
    return _should_allow_env_fallback()


def get_apca_env() -> ApcaEnv:
    """
    Load APCA_* env vars and normalize the base URL (strip trailing slash).
    These values are fetched via get_secret.
    """
    key_id = _get_required("APCA_API_KEY_ID")
    secret_key = _get_required("APCA_API_SECRET_KEY")
    base_url = _get_required("APCA_API_BASE_URL")
    return ApcaEnv(
        key_id=key_id,
        secret_key=secret_key,
        trading_host=_norm_host(base_url),
        data_host=_norm_host(os.getenv("ALPACA_DATA_HOST", "https://data.alpaca.markets")), # Data host might be config
    )


def assert_apca_env() -> None:
    """
    Fail fast at startup if APCA_* is missing.
    """
    _ = get_apca_env()


def assert_valid_alpaca_base_url(url: str, agent_mode: str, trading_mode: str) -> str:
    """
    Validate the Alpaca base URL based on agent and trading modes.
    """
    if url is None or str(url).strip() == "":
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

    raw = str(url).strip()
    lowered = raw.lower()

    # Explicit hard-fail: never allow live trading host in paper mode.
    if trading_mode == "paper" and _looks_like_live_trading_host(raw):
        raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden in paper mode: {raw!r}")

    # Basic URL validation.
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    # Allow paper-api.alpaca.markets for paper, or api.alpaca.markets for live.
    # Host validation might need to be more specific based on trading_mode.
    if not (parsed.hostname or "").lower().endswith("alpaca.markets"):
        raise RuntimeError(f"REFUSED: Alpaca base URL host is not alpaca.markets: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")

    normalized = raw[:-1] if raw.endswith("/") else raw
    return normalized

# --- Helper functions ---
# These are used within env.py and should ideally also use get_secret if they fetch secrets.
# However, _looks_like_live_trading_host is a utility and doesn't fetch secrets.
# _norm_host is also a utility.

def _norm_host(host: str) -> str:
    host = host.strip()
    return host[:-1] if host.endswith("/") else host

def _looks_like_live_trading_host(host: str) -> bool:
    """
    Best-effort detection of the live trading host.
    Used only to set sensible defaults (not security enforcement).
    """
    try:
        netloc = urlparse(host).netloc.lower()
    except Exception:
        netloc = host.lower()
    return "api.alpaca.markets" in netloc and "paper-api.alpaca.markets" not in netloc

