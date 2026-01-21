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
    v = os.getenv(name)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    if required:
        raise RuntimeError(f"Missing required env var: {name}")
    return default


def get_firebase_project_id(*, required: bool = False) -> str:
    v = (
        get_env("FIREBASE_PROJECT_ID", default=None)
        or get_env("FIRESTORE_PROJECT_ID", default=None)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None)
        or get_env("GCP_PROJECT", default=None)
    )
    if v:
        return str(v)
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
    if required:
        raise RuntimeError("Missing required env var: APCA_API_KEY_ID")
    return ""


def get_alpaca_api_key(*, required: bool = True) -> str:
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str:
    v = get_env("APCA_API_SECRET_KEY", default=None)
    v = v or get_env("ALPACA_SECRET_KEY", default=None)
    v = v or get_env("ALPACA_API_SECRET_KEY", default=None)
    v = v or get_env("APCA_API_SECRET", default=None)
    if v:
        s = str(v).strip()
        if s:
            os.environ.setdefault("APCA_API_SECRET_KEY", s)
            return s
    if required:
        raise RuntimeError("Missing required env var: APCA_API_SECRET_KEY")
    return ""


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Absolute safety boundary: allow ONLY Alpaca paper trading API base URLs.
    """
    if url is None or str(url).strip() == "":
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

    raw = str(url).strip()
    # Normalize: keep path, strip trailing slash.
    raw = raw[:-1] if raw.endswith("/") else raw
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
        raise RuntimeError(f"REFUSED: Alpaca base URL must be paper host: {raw!r}")

    return raw


def get_alpaca_api_base_url(*, required: bool = True) -> str:
    v = get_env("APCA_API_BASE_URL", default=None)
    v = v or get_env("ALPACA_TRADING_HOST", default=None)
    v = v or get_env("ALPACA_API_BASE_URL", default=None)
    v = v or get_env("ALPACA_API_URL", default=None)
    if v:
        s = str(v).strip()
        s = s[:-1] if s.endswith("/") else s
        if s:
            os.environ.setdefault("APCA_API_BASE_URL", s)
            return assert_paper_alpaca_base_url(s)
    if required:
        raise RuntimeError("Missing required env var: APCA_API_BASE_URL")
    return ""

