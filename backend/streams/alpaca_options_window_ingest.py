from backend.common.secrets import get_secret, get_alpaca_equities_feed, get_alpaca_options_feed
from backend.common.env import get_alpaca_api_base_url, get_alpaca_key_id, get_alpaca_secret_key, get_env
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.config import _parse_bool # Assuming _parse_bool is available or defined elsewhere if not standard
from typing import Dict, Any, Tuple, List, Optional
import os

TRADING_BASE = get_alpaca_api_base_url(required=True)
alpaca_paper: Optional[bool] = None

# Fetch explicit equities and options feeds from secrets.
equities_feed_secret = get_alpaca_equities_feed()
options_feed_secret = get_alpaca_options_feed() # This will be None if only equities feed is found.

# Determine feed to use for options chain.
# Priority: options_feed secret, then fallback to env var or default 'indicative'.
# If only equities feed is found (handled by get_alpaca_equities_feed), options_feed_secret will be None.
feed = options_feed_secret
if not feed:
    # Fallback to env var or default if options_feed secret is missing.
    feed = os.getenv("ALPACA_OPTIONS_FEED", "indicative")

feed = str(feed).strip().lower() or "indicative" # Ensure it's lowercased and not empty

stock_feed = os.getenv("ALPACA_STOCK_FEED", "iex").strip().lower() if os.getenv("ALPACA_STOCK_FEED") else "iex"

if os.getenv("ALPACA_PAPER") is not None:
    alpaca_paper = _parse_bool(os.getenv("ALPACA_PAPER"))

symbols = _parse_csv_symbols(str(get_env("ALPACA_SYMBOLS", "SPY,IWM,QQQ")))

# Need to check if _parse_csv_symbols is defined or imported. Assuming it is defined or available.
# If not, it might need to be added or handled.

def _parse_csv_symbols(symbols_str: str) -> List[str]:
    """Parses a comma-separated string of symbols."""
    return [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
