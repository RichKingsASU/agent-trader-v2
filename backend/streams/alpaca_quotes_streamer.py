from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env
import os

LAST_MARKETDATA_SOURCE: str = "alpaca_quotes_streamer"
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")

alpaca = load_alpaca_env()
SYMBOLS = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]
FEED = get_secret("ALPACA_DATA_FEED", fail_if_missing=False) or "iex"
FEED = FEED.strip().lower() or "iex"

if not SYMBOLS:
    raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")