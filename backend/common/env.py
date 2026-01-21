from __future__ import annotations

import os
from urllib.parse import urlparse

from backend.common.secrets import get_secret

TRUTHY = {"1", "true", "t", "yes", "y", "on"}

def _get_required(name: str, default: Any = None, *, required: bool = True) -> Any:
    """
    Reads an environment variable, falling back to Secret Manager if available.
    If required and not found, raises RuntimeError.
    """
    # Prefer Secret Manager for sensitive values.
    value = get_secret(name, fail_if_missing=False)
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

