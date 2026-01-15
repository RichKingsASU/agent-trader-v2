"""
Alpaca REST (no alpaca-py) historical 1m bars backfill helpers.

Constraints (intentional):
- Third-party deps: ONLY `requests` and `psycopg2` (plus stdlib).
- No Pub/Sub usage.
- No secret access at import time (callers must pass credentials or read env at runtime).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

import requests
import psycopg2
import psycopg2.extras


def _isoformat_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Assume UTC if caller provided naive datetimes.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_alpaca_ts(ts: str) -> datetime:
    # Alpaca returns RFC3339, typically with "Z" suffix.
    # datetime.fromisoformat doesn't accept "Z" directly.
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class AlpacaRestAuth:
    api_key_id: str
    api_secret_key: str


def fetch_alpaca_bars_1m(
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    auth: AlpacaRestAuth,
    feed: str = "iex",
    base_url: str = "https://data.alpaca.markets",
    adjustment: str = "raw",
    timeout_s: float = 20.0,
    max_pages: int = 10_000,
    limit_per_page: int = 10_000,
) -> list[dict[str, Any]]:
    """
    Fetch 1-minute bars via Alpaca Data REST API (no alpaca-py).

    Returns a list of dicts with canonical fields:
      - symbol, ts, open, high, low, close, volume
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required")

    if limit_per_page <= 0 or limit_per_page > 10_000:
        raise ValueError("limit_per_page must be within 1..10000")

    url = f"{base_url.rstrip('/')}/v2/stocks/{sym}/bars"
    headers = {
        "APCA-API-KEY-ID": auth.api_key_id,
        "APCA-API-SECRET-KEY": auth.api_secret_key,
        "Accept": "application/json",
        "User-Agent": "agenttrader/ingestion-alpaca-rest-backfill",
    }

    params: dict[str, Any] = {
        "timeframe": "1Min",
        "start": _isoformat_z(start),
        "end": _isoformat_z(end),
        "limit": int(limit_per_page),
        "adjustment": adjustment,
        "feed": str(feed or "iex").strip().lower(),
    }

    out: list[dict[str, Any]] = []
    page_token: str | None = None

    with requests.Session() as sess:
        for _page in range(max_pages):
            if page_token:
                params["page_token"] = page_token
            else:
                params.pop("page_token", None)

            resp = sess.get(url, headers=headers, params=params, timeout=timeout_s)
            if resp.status_code >= 400:
                # Keep message compact but informative for callers/loggers.
                raise RuntimeError(f"Alpaca bars fetch failed: status={resp.status_code} body={resp.text[:500]}")

            payload = resp.json() or {}
            bars = payload.get("bars") or []
            if not isinstance(bars, list):
                raise RuntimeError("Unexpected Alpaca response shape: 'bars' is not a list")

            for b in bars:
                # Alpaca fields: t,o,h,l,c,v (plus others we ignore)
                ts_raw = b.get("t")
                if not ts_raw:
                    continue
                out.append(
                    {
                        "symbol": sym,
                        "ts": _parse_alpaca_ts(str(ts_raw)),
                        "open": float(b.get("o") or 0.0),
                        "high": float(b.get("h") or 0.0),
                        "low": float(b.get("l") or 0.0),
                        "close": float(b.get("c") or 0.0),
                        "volume": int(b.get("v") or 0),
                    }
                )

            page_token = payload.get("next_page_token") or None
            if not page_token:
                break

    return out


def upsert_market_data_1m_bars(
    *,
    db_url: str,
    bars: Iterable[dict[str, Any]],
    session: str | None = None,
    commit: bool = True,
) -> int:
    """
    Upsert 1-minute bars into `public.market_data_1m` using psycopg2.

    Expects each bar dict to include:
      - symbol (str), ts (datetime), open/high/low/close (float-ish), volume (int-ish)
    """
    if not (db_url or "").strip():
        raise ValueError("db_url is required")

    rows: list[tuple[Any, ...]] = []
    for b in bars:
        rows.append(
            (
                str(b["symbol"]).strip().upper(),
                b["ts"],
                b.get("open"),
                b.get("high"),
                b.get("low"),
                b.get("close"),
                b.get("volume"),
                session,
            )
        )

    if not rows:
        return 0

    sql = """
        INSERT INTO public.market_data_1m (
            symbol, ts, open, high, low, close, volume, session
        ) VALUES %s
        ON CONFLICT (symbol, ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            session = COALESCE(EXCLUDED.session, public.market_data_1m.session)
    """

    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    sql,
                    rows,
                    template="(%s,%s,%s,%s,%s,%s,%s,%s)",
                    page_size=1000,
                )
        if commit:
            conn.commit()
    finally:
        conn.close()

    return len(rows)

