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
    return ApcaEnv(api_key_id=key_id, api_secret_key=secret_key, api_base_url=base_url)


def assert_apca_env() -> None:
    """
    Fail fast at startup if APCA_* is missing.
    """
    _ = get_apca_env()

