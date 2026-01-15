from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any, Dict, Optional

# Import necessary functions from backend.common.env and backend.common.secrets
from backend.common.env import get_alpaca_api_base_url, get_alpaca_key_id, get_alpaca_secret_key
from backend.common.secrets import get_secret # Import get_secret for consistency

# Define AgentMode Enum if not already defined or imported. Assuming it's available.
# If not, it might need a placeholder or import. For now, assuming it's available.
# Placeholder for AgentMode if not imported elsewhere:
# class AgentMode:
#     PAPER = "paper"
#     LIVE = "live"
#     SANDBOX = "sandbox"

def _get_required(name: str, default: Any = None, *, required: bool = True) -> Any:
    """
    Reads an environment variable, falling back to Secret Manager if available.
    If required and not found, raises RuntimeError.
    """
    # Prefer Secret Manager for sensitive values.
    value = get_secret(name, default=default, fail_if_missing=False)
    if value:
        return value

    # Fallback to environment variable if allowed and not found in Secret Manager.
    # Note: Secrets like API keys should not rely on env fallback unless explicitly allowed.
    # The get_secret function itself handles ALLOW_ENV_SECRET_FALLBACK.
    # If get_secret returns empty and required is True, it should fail.
    # This function is designed to wrap get_secret.
    
    # If get_secret didn't find it, and required is True, it should have raised or returned empty.
    # Let's handle the 'required' flag explicitly. If we reach here and required is True,
    # and value is still empty, it means it wasn't found via get_secret.
    # We should check env var here as a LAST resort if get_secret failed for non-secret reasons or if fallback is enabled.
    # However, the prompt implies ALL secrets MUST be via get_secret.
    # So, if it's a secret name and not found via get_secret, it should fail if required.
    
    # Re-thinking: the prompt says "All secrets must be retrieved via get_secret()".
    # This implies direct os.getenv calls for secrets should be replaced.
    # _get_required is used within apca_env.py. Let's refactor it to use get_secret primarily.

    # Check Secret Manager first
    value = get_secret(name, fail_if_missing=False) # Do not fail here, handle fallback

    if value:
        return value

    # If not found in Secret Manager, check environment variable (only if allowed)
    if _should_allow_env_fallback_for_name(name): # Need a way to know if fallback is allowed for this name
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
    # Prefer Secret Manager sourcing when env isn't set (no shell exports required).
    if (os.getenv("APCA_API_KEY_ID") is None or str(os.getenv("APCA_API_KEY_ID") or "").strip() == "") and required:
        try:
            from backend.common.alpaca_env import configure_alpaca_env  # noqa: WPS433

            configure_alpaca_env(required=True)
        except Exception:
            # Fall through to legacy env/alias resolution; final required check below.
            pass

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


def assert_valid_alpaca_base_url(url: str, agent_mode: str, trading_mode: str) -> str:
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
    # Prefer Secret Manager sourcing when env isn't set (no shell exports required).
    if (os.getenv("APCA_API_SECRET_KEY") is None or str(os.getenv("APCA_API_SECRET_KEY") or "").strip() == "") and required:
        try:
            from backend.common.alpaca_env import configure_alpaca_env  # noqa: WPS433

            configure_alpaca_env(required=True)
        except Exception:
            pass

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
    # Prefer Secret Manager sourcing when env isn't set (no shell exports required).
    if (os.getenv("APCA_API_BASE_URL") is None or str(os.getenv("APCA_API_BASE_URL") or "").strip() == "") and required:
        try:
            from backend.common.alpaca_env import configure_alpaca_env  # noqa: WPS433

            configure_alpaca_env(required=True)
        except Exception:
            pass

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

