"""
Shared Alpaca environment helpers for backend/streams scripts.

Goals:
- Standardize on ALPACA_TRADING_HOST and ALPACA_DATA_HOST for base URLs.
- Standardize on ALPACA_API_KEY and ALPACA_SECRET_KEY for API keys.
- Keep defaults safe: paper trading defaults to paper host, market data defaults to data host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key


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

    Keys are read from ALPACA_API_KEY and ALPACA_SECRET_KEY
    (with back-compat support for ALPACA_KEY_ID).
    """
    key_id = get_alpaca_key_id(required=require_keys)
    secret_key = get_alpaca_secret_key(required=require_keys)

    trading_host = _norm_host(
        os.getenv("ALPACA_TRADING_HOST", "https://paper-api.alpaca.markets")
    )
    data_host = _norm_host(os.getenv("ALPACA_DATA_HOST", "https://data.alpaca.markets"))

    # Back-compat with alpaca-trade-api env var names.
    #
    # Requirement: ensure APCA_API_BASE_URL is explicitly set to the paper endpoint
    # by default. We do this *without* overriding a caller-provided value.
    #
    # alpaca-trade-api expects:
    # - APCA_API_KEY_ID
    # - APCA_API_SECRET_KEY
    # - APCA_API_BASE_URL
    os.environ.setdefault("APCA_API_BASE_URL", trading_host)
    if key_id:
        os.environ.setdefault("APCA_API_KEY_ID", key_id)
    if secret_key:
        os.environ.setdefault("APCA_API_SECRET_KEY", secret_key)

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

