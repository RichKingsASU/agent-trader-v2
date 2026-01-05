# agenttrader/backend/utils/session.py
from datetime import datetime, time

from backend.common.timeutils import to_nyse_time

def get_market_session(timestamp_utc: datetime) -> str:
    """
    Classifies a UTC timestamp into a market session for America/New_York.
    """
    ts_ny = to_nyse_time(timestamp_utc)
    t_ny = ts_ny.time()

    pre_market_start = time(4, 0)
    market_open = time(9, 30)
    market_close = time(16, 0)
    after_market_end = time(20, 0)

    # Check for weekday (Monday=0, Sunday=6)
    if ts_ny.weekday() >= 5:
        return "CLOSED"

    if pre_market_start <= t_ny < market_open:
        return "PRE"
    elif market_open <= t_ny < market_close:
        return "REGULAR"
    elif market_close <= t_ny < after_market_end:
        return "AFTER"
    else:
        return "CLOSED"
