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

# NOTE:
# This module is covered by CI's `python -m compileall .` gate.
# Keep top-level definitions flush-left (avoid accidental indentation).


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    """
    Read an environment variable with optional Secret Manager fallback.

    Order:
    - Secret Manager (best-effort; never raises here)
    - os.environ
    - default
    """
    try:
        v = get_secret(name, fail_if_missing=False)
    except Exception:
        v = ""

    if v is not None and str(v).strip() != "":
        return str(v).strip()

    env_v = os.getenv(name)
    if env_v is not None and str(env_v).strip() != "":
        return str(env_v).strip()

    if required:
        raise RuntimeError(f"Missing required env var: {name}")

    return default


def get_firebase_project_id(*, required: bool = False) -> str:
    v = (
        os.getenv("FIREBASE_PROJECT_ID")
        or os.getenv("FIRESTORE_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
    )
    if v and str(v).strip():
        return str(v).strip()
    if required:
        raise RuntimeError(
            "Missing required env var: FIREBASE_PROJECT_ID (or FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT / GCP_PROJECT)"
        )
    return ""


def get_vertex_ai_project_id(*, required: bool = False) -> str:
    v = get_env("VERTEX_AI_PROJECT_ID", default=None) or get_firebase_project_id(required=required)
    return str(v or "")


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    return str(get_env("VERTEX_AI_LOCATION", default=default) or default)


def get_vertex_ai_model_id(*, default: str = "gemini-2.5-flash") -> str:
    return str(get_env("VERTEX_AI_MODEL_ID", default=default) or default)


def get_alpaca_key_id(*, required: bool = True) -> Optional[str]:
    v = get_env("APCA_API_KEY_ID", default=None, required=required)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def get_alpaca_api_key(*, required: bool = True) -> Optional[str]:
    # Alias used by some modules.
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> Optional[str]:
    v = get_env("APCA_API_SECRET_KEY", default=None, required=required)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def get_alpaca_api_base_url(*, required: bool = True) -> Optional[str]:
    # Default to paper URL for safety.
    v = get_env("APCA_API_BASE_URL", default="https://paper-api.alpaca.markets", required=required)
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None if not required else ""
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

    host = (parsed.hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: live Alpaca trading host is forbidden in paper mode: {raw!r}")

    return raw[:-1] if raw.endswith("/") else raw


def assert_valid_alpaca_base_url(url: str, agent_mode: str, trading_mode: str) -> str:
    """
    Conservative validation helper used by scripts/tests.
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

