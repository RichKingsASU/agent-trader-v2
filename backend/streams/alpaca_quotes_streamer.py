from __future__ import annotations

import os
from dataclasses import dataclass

from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env


LAST_MARKETDATA_SOURCE: str = "alpaca_quotes_streamer"


@dataclass(frozen=True)
class QuotesStreamerConfig:
    db_url: str
    symbols: list[str]
    feed: str
    alpaca: object


_cfg: QuotesStreamerConfig | None = None


def get_config() -> QuotesStreamerConfig:
    """
    Resolve runtime config at runtime (never at import time).
    """

    global _cfg
    if _cfg is not None:
        return _cfg

    db_url = get_secret("DATABASE_URL", required=True)
    alpaca = load_alpaca_env()
    symbols = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]
    if not symbols:
        raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")

    feed = str(get_secret("ALPACA_DATA_FEED", required=False, default="iex") or "iex").strip().lower() or "iex"

    _cfg = QuotesStreamerConfig(db_url=db_url, symbols=symbols, feed=feed, alpaca=alpaca)
    return _cfg