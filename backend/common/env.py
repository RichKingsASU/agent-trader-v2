from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Optional

from backend.common.secrets import get_secret


def get_env(name: str, *, default: Optional[str] = None, required: bool = False) -> str:
    """
    Read non-secret runtime configuration from the environment.
    """

    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return str(default or "")
    return str(v).strip()


# ---------------------------------------------------------------------------
# Canonical Alpaca secret accessors (no aliases; strict contract)
# ---------------------------------------------------------------------------
def get_alpaca_key_id(*, required: bool = True) -> str:
    return get_secret("APCA_API_KEY_ID", required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str:
    return get_secret("APCA_API_SECRET_KEY", required=required)


def get_alpaca_api_base_url(*, required: bool = False) -> str:
    # Default is paper base URL; still routed through secrets contract.
    return get_secret("APCA_API_BASE_URL", required=required, default="https://paper-api.alpaca.markets")


def assert_paper_alpaca_base_url(url: str) -> str:
    """
    Safety boundary: refuse non-paper Alpaca trading hosts.
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
        raise RuntimeError(
            f"REFUSED: paper trading requires Alpaca host 'paper-api.alpaca.markets'. Got: {raw!r}"
        )
    return raw[:-1] if raw.endswith("/") else raw

