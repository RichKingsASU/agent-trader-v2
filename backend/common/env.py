from __future__ import annotations

import os
from urllib.parse import urlparse

from backend.common.secrets import get_secret

TRUTHY = {"1", "true", "t", "yes", "y", "on"}


def _norm_url(url: str) -> str:
    s = str(url).strip()
    return s[:-1] if s.endswith("/") else s


def _first_nonempty(*values: str | None) -> str | None:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def _get_secret_any(names: list[str], *, required: bool) -> str:
    for n in names:
        try:
            v = get_secret(n, fail_if_missing=False)
        except Exception:
            v = ""
        if v and str(v).strip():
            return str(v).strip()
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

