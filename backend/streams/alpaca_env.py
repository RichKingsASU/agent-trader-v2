"""
Shared Alpaca environment helpers for backend/streams scripts.

Goals:
- Standardize Alpaca credentials on the official Alpaca SDK env vars:
  - APCA_API_KEY_ID
  - APCA_API_SECRET_KEY
  - APCA_API_BASE_URL

Non-credential stream configuration (symbols/feed/data host) remains separate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.common.env import (
    get_alpaca_api_base_url,
    get_alpaca_key_id,
    get_alpaca_secret_key,
)


def _first_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def _norm_host(host: str) -> str:
    host = host.strip()
    return host[:-1] if host.endswith("/") else host


def _looks_like_live_trading_host(host: str) -> bool:
    """
    Best-effort detection of the live trading host.
    Used only to set sensible defaults (not security enforcement).
    """
    try:
        netloc = urlparse(host).netloc.lower()
    except Exception:
        netloc = host.lower()
    return "api.alpaca.markets" in netloc and "paper-api.alpaca.markets" not in netloc


@dataclass(frozen=True)
class AlpacaEnv:
    key_id: str
    secret_key: str
    trading_host: str
    data_host: str

    @property
    def trading_base_v2(self) -> str:
        return f"{self.trading_host}/v2"

    @property
    def data_base_v2(self) -> str:
        return f"{self.data_host}/v2"

    @property
    def data_stocks_base_v2(self) -> str:
        return f"{self.data_host}/v2/stocks"


def load_alpaca_env(*, require_keys: bool = True) -> AlpacaEnv:
    """
    Loads Alpaca env vars.

    Credentials are read from official Alpaca SDK env vars:
    - APCA_API_KEY_ID
    - APCA_API_SECRET_KEY
    - APCA_API_BASE_URL
    """
    key_id = get_alpaca_key_id(required=require_keys)
    secret_key = get_alpaca_secret_key(required=require_keys)

    trading_host = _norm_host(get_alpaca_api_base_url(required=require_keys) or "https://paper-api.alpaca.markets")
    from backend.common.secrets import get_secret

    data_host = _norm_host(get_secret("ALPACA_DATA_HOST", required=False, default="https://data.alpaca.markets"))

    # If keys are optional, return empty strings to simplify callers.
    return AlpacaEnv(
        key_id=key_id or "",
        secret_key=secret_key or "",
        trading_host=trading_host,
        data_host=data_host,
    )


def default_trading_paper_flag(trading_host: str) -> bool:
    """
    For alpaca-py TradingClient(paper=...), derive a default based on the host.
    If the host appears to be live trading, set paper=False; otherwise paper=True.
    """
    return not _looks_like_live_trading_host(trading_host)

