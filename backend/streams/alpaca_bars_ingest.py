from backend.common.secrets import get_secret, get_alpaca_equities_feed, get_alpaca_options_feed
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
import os

db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("Missing required env var: DATABASE_URL")

    from backend.common.secrets import get_database_url  # noqa: WPS433

    db_url = get_database_url(required=True)
    alpaca = load_alpaca_env(require_keys=True)
    base = alpaca.data_stocks_base_v2
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}

    logger.info("Starting short-window ingest...")
    logger.info("Resolved target table: %s | symbols: %s | feed: %s", TARGET_TABLE, ", ".join(SYMS), FEED)
    total_upserted = 0

# Determine the feed to use:
# Priority: 1. equities_feed, 2. options_feed (if only one found, treat as equities), 3. default 'iex'.
feed = equities_feed
if not feed and options_feed:
    feed = options_feed # Treat options feed as equities if it's the only one found.

# Fallback to default if feed is still empty.
# Removed direct fallback to os.getenv("ALPACA_FEED", ...) as per requirement.
feed = feed or "iex" # Default to 'iex' if no secrets are found.
feed = str(feed).strip().lower() # Ensure it's lowercased

syms = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",") if s.strip()]
days = int(os.getenv("ALPACA_BACKFILL_DAYS", "5"))