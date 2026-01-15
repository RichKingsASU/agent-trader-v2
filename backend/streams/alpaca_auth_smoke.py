from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env, AlpacaEnv
import os

def _truthy(v: str | None) -> bool:
    return bool(str(v or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"})

def run_smoke_tests() -> bool:
    return _truthy(os.getenv("RUN_ALPACA_AUTH_SMOKE_TESTS"))

# If RUN_ALPACA_AUTH_SMOKE_TESTS is set, load secrets and try to connect.
# If run_smoke_tests() is false, return early.
if run_smoke_tests():
    env = load_alpaca_env(require_keys=False) # Use require_keys=False as these are just smoke tests
    alpaca_data_stream_ws_url = get_secret("ALPACA_DATA_STREAM_WS_URL", fail_if_missing=False) or ""
    alpaca_data_feed = get_secret("ALPACA_DATA_FEED", fail_if_missing=False) or "iex"
    alpaca_data_feed = alpaca_data_feed.strip().lower() or "iex"
