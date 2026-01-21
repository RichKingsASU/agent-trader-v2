from backend.common.secrets import get_secret, get_alpaca_equities_feed, get_alpaca_options_feed
from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key
from backend.common.timeutils import parse_alpaca_timestamp
import os

DEFAULT_ALPACA_DATA_HOST = "https://data.alpaca.markets"

def resolve_alpaca_credentials() -> tuple[str, str]:
    api_key = get_alpaca_key_id(required=True)
    secret_key = get_alpaca_secret_key(required=True)
    return api_key, secret_key

def resolve_symbols_str() -> str:
    return os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")

def resolve_feed() -> str:
    # Task 1: Resolve ALPACA_FEED naming conflict.
    # Fetch explicit equities and options feeds from secrets.
    equities_feed = get_alpaca_equities_feed()
    options_feed = get_alpaca_options_feed()  # This will be None if only equities feed is found.

    # Determine the feed to use for runtime.
    # Priority: 1. equities_feed, 2. options_feed (if only one found, treat as equities), 3. default 'iex'.
    feed = equities_feed
    if not feed and options_feed:
        feed = options_feed  # Treat options feed as equities if it's the only one found.

    # If feed is still empty after checking secrets, use default 'iex'.
    # Removed fallback to os.getenv("ALPACA_FEED", ...) as per requirement.
    feed = feed or "iex"
    return str(feed).strip().lower() or "iex"  # Ensure it's lowercased and not empty

def resolve_data_base() -> str:
    try:
        data_base = get_secret("ALPACA_DATA_HOST", fail_if_missing=False)
    except Exception:
        data_base = None

    if not data_base:
        data_base = DEFAULT_ALPACA_DATA_HOST

    return str(data_base).rstrip("/")


def main() -> int:
    # Resolve runtime config (no secret access at import time).
    _api_key, _secret_key = resolve_alpaca_credentials()
    _symbols_str = resolve_symbols_str()
    _feed = resolve_feed()
    _data_base = resolve_data_base()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())