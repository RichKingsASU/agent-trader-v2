"""
Canonical Alpaca authentication environment loader.

Repo contract (runtime):
  - APCA_API_KEY_ID
  - APCA_API_SECRET_KEY
  - APCA_API_BASE_URL

No runtime fallback to legacy ALPACA_* env vars. Fail fast with a clear error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _require_non_empty(name: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        raise RuntimeError(
            "Missing required Alpaca environment variables. "
            "Set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and APCA_API_BASE_URL."
        )
    v = str(raw).strip()
    if v == "":
        raise RuntimeError(
            f"Env var {name} is set but empty. "
            "Set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and APCA_API_BASE_URL to non-empty values."
        )
    return v


def _norm_url(url: str) -> str:
    u = str(url).strip()
    return u[:-1] if u.endswith("/") else u


@dataclass(frozen=True)
class AlpacaAuthEnv:
    """
    Canonical Alpaca auth env values (already validated).
    """

    api_key_id: str
    api_secret_key: str
    api_base_url: str

    # Convenience aliases used across SDKs.
    @property
    def key_id(self) -> str:  # alpaca-trade-api naming
        return self.api_key_id

    @property
    def secret_key(self) -> str:  # alpaca-trade-api naming
        return self.api_secret_key

    @property
    def base_url(self) -> str:  # alpaca-trade-api naming
        return self.api_base_url

    @property
    def headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self.api_key_id, "APCA-API-SECRET-KEY": self.api_secret_key}


def load_alpaca_auth_env() -> AlpacaAuthEnv:
    """
    Load and validate Alpaca auth env vars (APCA_* only).
    """

    key_id = _require_non_empty("APCA_API_KEY_ID")
    secret_key = _require_non_empty("APCA_API_SECRET_KEY")
    base_url = _norm_url(_require_non_empty("APCA_API_BASE_URL"))
    return AlpacaAuthEnv(api_key_id=key_id, api_secret_key=secret_key, api_base_url=base_url)

