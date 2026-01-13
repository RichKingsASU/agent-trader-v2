"""
APCA_* environment helpers (official Alpaca SDK env vars only).

Rules:
- Runtime code must read ONLY:
  - APCA_API_KEY_ID
  - APCA_API_SECRET_KEY
  - APCA_API_BASE_URL
- No ALPACA_* fallback logic at runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ApcaEnv:
    api_key_id: str
    api_secret_key: str
    api_base_url: str


def _get_required(name: str) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v).strip()


def get_apca_env() -> ApcaEnv:
    """
    Load APCA_* env vars and normalize the base URL (strip trailing slash).
    """
    key_id = _get_required("APCA_API_KEY_ID")
    secret_key = _get_required("APCA_API_SECRET_KEY")
    base_url = _get_required("APCA_API_BASE_URL")
    base_url = base_url[:-1] if base_url.endswith("/") else base_url
    base_url = assert_paper_alpaca_base_url(base_url)
    return ApcaEnv(api_key_id=key_id, api_secret_key=secret_key, api_base_url=base_url)


def assert_apca_env() -> None:
    """
    Fail fast at startup if APCA_* is missing.
    """
    _ = get_apca_env()


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

    # Normalize (preserve any path; just strip trailing slash).
    normalized = raw[:-1] if raw.endswith("/") else raw
    return normalized

