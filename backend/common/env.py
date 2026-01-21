from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any, Optional


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return str(v).strip()


def get_alpaca_key_id(*, required: bool = True) -> str | None:
    v = get_env("APCA_API_KEY_ID", None, required=required)
    return str(v).strip() if v is not None else None


def get_alpaca_api_key(*, required: bool = True) -> str | None:
    # Alias used in some modules.
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str | None:
    v = get_env("APCA_API_SECRET_KEY", None, required=required)
    return str(v).strip() if v is not None else None


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
        raise RuntimeError(f"Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    host = (parsed.hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise RuntimeError(f"REFUSED: paper trading requires https://paper-api.alpaca.markets (got {raw!r})")
    return raw[:-1] if raw.endswith("/") else raw


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

