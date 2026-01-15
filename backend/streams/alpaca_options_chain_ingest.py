"""
Alpaca options chain ingest (entrypoint).

This module intentionally avoids resolving secrets at import time.
"""

from __future__ import annotations

import os

from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key
from backend.common.secrets import get_alpaca_equities_feed, get_alpaca_options_feed, get_secret


def main() -> None:
    # Secrets resolved via backend.common.secrets (runtime only).
    _ = get_alpaca_key_id(required=True)
    _ = get_alpaca_secret_key(required=True)

    equities_feed = get_alpaca_equities_feed()
    options_feed = get_alpaca_options_feed()
    feed = (options_feed or "indicative").strip().lower() or "indicative"
    _fallback = get_secret("ALPACA_OPTIONS_FEED", required=False, default="")  # explicitly allowed key
    if not options_feed and _fallback:
        feed = str(_fallback).strip().lower() or feed

    max_pages = int(os.getenv("ALPACA_OPTIONS_MAX_PAGES", "3"))
    symbols = [s.strip().upper() for s in (os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ") or "").split(",") if s.strip()]

    # Stub: actual ingestion logic lives elsewhere / is intentionally omitted here.
    _ = (equities_feed, feed, max_pages, symbols)


if __name__ == "__main__":
    main()

