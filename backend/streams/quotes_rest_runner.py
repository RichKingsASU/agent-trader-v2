import os, time, logging
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import psycopg2
from psycopg2.extras import execute_values
from tenacity import retry, wait_exponential, stop_after_attempt

from backend.common.alpaca_env import configure_alpaca_env
from backend.common.secrets import get_database_url
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

# --- Standard Header ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_ = configure_alpaca_env(required=True)
DB_URL = get_database_url(required=True)
alpaca = load_alpaca_env(require_keys=True)
ALPACA_KEY = alpaca.key_id
ALPACA_SEC = alpaca.secret_key
SYMBOLS = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",")
FEED = os.getenv("ALPACA_FEED", "iex")
ALPACA_HOST = alpaca.data_host

session = requests.Session()
session.headers.update(
    {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SEC,
    }
)
# --- End Standard Header ---

alpaca = load_alpaca_env()
API_KEY = alpaca.key_id
SECRET_KEY = alpaca.secret_key
SYMBOLS = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]

# Task 1: Resolve ALPACA_FEED naming conflict. Fetch explicit feeds.
equities_feed = get_alpaca_equities_feed()
options_feed = get_alpaca_options_feed() # This will be None if only equities feed is found.

# Determine the feed to use:
# Priority: 1. equities_feed, 2. options_feed (if only one found, treat as equities), 3. env var, 4. default 'iex'.
feed = equities_feed
if not feed and options_feed:
    feed = options_feed # Treat options feed as equities if it's the only one found.

# Fallback to env var or default if feed is still empty.
feed = feed or os.getenv("ALPACA_FEED", "iex") # Fallback to env var or default 'iex'
feed = str(feed).strip().lower() or "iex" # Ensure it's lowercased and not empty

