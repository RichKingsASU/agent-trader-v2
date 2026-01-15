"""
Alpaca options window ingest (entrypoint).

This module intentionally avoids resolving secrets at import time.
"""

from __future__ import annotations

import os

from backend.common.env import get_alpaca_api_base_url, get_alpaca_key_id, get_alpaca_secret_key
from backend.common.secrets import get_alpaca_equities_feed, get_alpaca_options_feed, get_secret


def main() -> None:
    _ = get_alpaca_key_id(required=True)
    _ = get_alpaca_secret_key(required=True)

    trading_base = get_alpaca_api_base_url(required=False)
    equities_feed = get_alpaca_equities_feed()
    options_feed = get_alpaca_options_feed()

    feed = (options_feed or "indicative").strip().lower() or "indicative"
    _fallback = get_secret("ALPACA_OPTIONS_FEED", required=False, default="")
    if not options_feed and _fallback:
        feed = str(_fallback).strip().lower() or feed

    stock_feed = (os.getenv("ALPACA_STOCK_FEED") or "iex").strip().lower() or "iex"
    symbols = [s.strip().upper() for s in (os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ") or "").split(",") if s.strip()]

    # Stub: actual ingestion logic lives elsewhere / is intentionally omitted here.
    _ = (trading_base, equities_feed, feed, stock_feed, symbols)


if __name__ == "__main__":
    main()

