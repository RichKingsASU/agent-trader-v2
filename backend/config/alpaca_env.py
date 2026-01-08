"""
Alpaca environment contract (repo standard).

Non-negotiable: use ONLY the official Alpaca SDK env vars:
  - APCA_API_KEY_ID
  - APCA_API_SECRET_KEY
  - APCA_API_BASE_URL

This module is the *single* place where Alpaca credential env vars are read.
All callers (REST + WebSocket) must import and use this helper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _get_required(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise KeyError(name)
    return str(v).strip()


def _norm_base_url(url: str) -> str:
    u = url.strip()
    u = u[:-1] if u.endswith("/") else u
    # Best-effort sanity check: allow http(s) URLs; keep message crisp.
    try:
        parsed = urlparse(u)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError
    except Exception as e:
        raise ValueError(f"Invalid APCA_API_BASE_URL: {url!r}") from e
    return u


@dataclass(frozen=True, slots=True)
class AlpacaEnv:
    key_id: str
    secret_key: str
    base_url: str

    @property
    def trading_base_v2(self) -> str:
        return f"{self.base_url}/v2"

    @property
    def data_host(self) -> str:
        # Alpaca market data REST base host (does not vary between paper/live).
        return "https://data.alpaca.markets"

    @property
    def data_base_v2(self) -> str:
        return f"{self.data_host}/v2"

    @property
    def data_stocks_base_v2(self) -> str:
        return f"{self.data_host}/v2/stocks"

    def auth_headers(self) -> dict[str, str]:
        # Used for direct REST calls to Alpaca endpoints.
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
        }


def load_alpaca_env() -> AlpacaEnv:
    """
    Load Alpaca credentials from env and fail fast if missing.
    """
    missing: list[str] = []
    try:
        key_id = _get_required("APCA_API_KEY_ID")
    except KeyError:
        missing.append("APCA_API_KEY_ID")
        key_id = ""

    try:
        secret_key = _get_required("APCA_API_SECRET_KEY")
    except KeyError:
        missing.append("APCA_API_SECRET_KEY")
        secret_key = ""

    try:
        base_url_raw = _get_required("APCA_API_BASE_URL")
        base_url = _norm_base_url(base_url_raw)
    except KeyError:
        missing.append("APCA_API_BASE_URL")
        base_url = ""
    except ValueError as e:
        # Base URL is present but malformed.
        raise RuntimeError(str(e)) from e

    if missing:
        missing_s = ", ".join(missing)
        raise RuntimeError(
            f"Missing required Alpaca env vars: {missing_s}. "
            "Set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and APCA_API_BASE_URL."
        )

    return AlpacaEnv(key_id=key_id, secret_key=secret_key, base_url=base_url)

