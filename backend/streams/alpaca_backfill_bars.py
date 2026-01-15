from __future__ import annotations

import os

from backend.common.secrets import get_alpaca_equities_feed, get_alpaca_options_feed, get_secret
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp


def main() -> None:
    # Resolve secrets at runtime (never at import time).
    db_url = get_secret("DATABASE_URL", required=True)
    alpaca = load_alpaca_env(require_keys=True)

    equities_feed = get_alpaca_equities_feed()
    options_feed = get_alpaca_options_feed()
    feed = (equities_feed or options_feed or "iex").strip().lower() or "iex"

    syms = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",") if s.strip()]
    days = int(os.getenv("ALPACA_BACKFILL_DAYS", "5"))

    # Intentionally left as a stub: this module is a config-only entrypoint.
    _ = (db_url, alpaca, feed, syms, days, normalize_alpaca_timestamp)


if __name__ == "__main__":
    main()