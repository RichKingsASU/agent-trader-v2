from __future__ import annotations

import os

from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key
from backend.common.secrets import get_alpaca_equities_feed, get_alpaca_options_feed, get_secret
from backend.common.timeutils import parse_alpaca_timestamp


def main() -> None:
    # Resolve secrets at runtime (never at import time).
    api_key = get_alpaca_key_id(required=True)
    secret_key = get_alpaca_secret_key(required=True)
    symbols_str = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")

    # Task 1: Resolve ALPACA_FEED naming conflict.
    equities_feed = get_alpaca_equities_feed()
    options_feed = get_alpaca_options_feed()  # None if only equities feed exists.

    feed = equities_feed or (options_feed or "iex")
    feed = str(feed).strip().lower() or "iex"

    data_base = str(get_secret("ALPACA_DATA_HOST", required=False, default="https://data.alpaca.markets") or "").rstrip("/")

    # Intentionally left as a stub: this script is a config-only example.
    _ = (api_key, secret_key, symbols_str, feed, data_base, parse_alpaca_timestamp)


if __name__ == "__main__":
    main()