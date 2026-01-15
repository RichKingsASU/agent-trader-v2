from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    """
    Read an environment variable.

    - If set (and non-empty), returns its value (string).
    - If not set, returns default.
    - If required=True and not set, raises RuntimeError.
    """
    v = os.getenv(name)
    if v is not None and v != "":
        return v
    if required:
        raise RuntimeError(f"Missing required env var: {name}")
    return default


def get_firebase_project_id(*, required: bool = False) -> str:
    """
    Resolve the Firebase/GCP project id.

    Preferred:
    - FIREBASE_PROJECT_ID

    Back-compat / fallbacks:
    - FIRESTORE_PROJECT_ID
    - GOOGLE_CLOUD_PROJECT (ADC default)
    """
    v = (
        get_env("FIREBASE_PROJECT_ID", default=None, required=False)
        or get_env("FIRESTORE_PROJECT_ID", default=None, required=False)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None, required=False)
    )
    if v:
        return str(v)
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


def get_alpaca_key_id(*, required: bool = True) -> str:
    """
    Returns the Alpaca API key id.

    Env contract (official Alpaca SDK):
    - APCA_API_KEY_ID
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

    # Explicit hard-fail: never allow live trading host.
    if "api.alpaca.markets" in lowered and "paper-api.alpaca.markets" not in lowered:
        raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden: {raw!r}")

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    if (parsed.hostname or "").lower() != "paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be paper host: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")

    normalized = raw[:-1] if raw.endswith("/") else raw
    return normalized

