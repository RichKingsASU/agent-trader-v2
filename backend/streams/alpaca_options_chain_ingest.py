from __future__ import annotations

import json
import os
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import requests

from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key, get_env
from backend.common.logging import init_structured_logging

init_structured_logging(service="alpaca-options-chain-ingest")
logger = logging.getLogger(__name__)


def _json_safe(v: Any) -> Any:
    """
    Recursively convert objects to JSON-safe primitives.

    - date/datetime -> ISO strings
    - Decimal -> float
    """
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        # Keep timezone info if present
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    return str(v)


def _alpaca_headers() -> Dict[str, str]:
    key = get_alpaca_key_id(required=True)
    secret = get_alpaca_secret_key(required=True)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def fetch_option_snapshots(
    *,
    underlying: str,
    feed: str,
    max_pages: int,
) -> Tuple[Dict[str, Any], int]:
    """
    Fetch option snapshots for an underlying via Alpaca Options Data API.

    Confirmed endpoint:
      GET https://data.alpaca.markets/v1beta1/options/snapshots/{UNDERLYING}

    Pagination:
      next_page_token (response) -> page_token (request)
    """
    url = f"https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}"
    headers = _alpaca_headers()

    all_snaps: Dict[str, Any] = {}
    page_token: Optional[str] = None
    pages_used = 0

    for _ in range(max_pages):
        params: Dict[str, Any] = {"feed": feed}
        if page_token:
            params["page_token"] = page_token

        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json() or {}

        snaps = payload.get("snapshots") or {}
        if isinstance(snaps, dict):
            all_snaps.update(snaps)

        pages_used += 1
        page_token = payload.get("next_page_token")
        if not page_token:
            break

    return all_snaps, pages_used


def _connect_db(db_url: str):
    """
    Lazily import a DB driver only when DATABASE_URL is set.
    Prefer psycopg (v3) if available, fall back to psycopg2.
    """
    try:
        import psycopg  # type: ignore

        return ("psycopg", psycopg.connect(db_url))
    except Exception:
        try:
            import psycopg2  # type: ignore

            return ("psycopg2", psycopg2.connect(db_url))
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "DATABASE_URL is set but neither psycopg nor psycopg2 is available. "
                "Install one (e.g. pip install psycopg[binary]) or unset DATABASE_URL for API-only mode."
            ) from e


def upsert_snapshots(
    *,
    db_url: str,
    snapshot_time: datetime,
    underlying_symbol: str,
    snapshots: Dict[str, Any],
) -> int:
    """
    Upsert into:
      public.alpaca_option_snapshots(underlying_symbol, option_symbol, snapshot_time, payload)
    PK(option_symbol, snapshot_time)
    """
    _, conn = _connect_db(db_url)
    try:
        with conn.cursor() as cur:
            rows = []
            for option_symbol, snapshot in (snapshots or {}).items():
                rows.append(
                    (
                        underlying_symbol,
                        option_symbol,
                        snapshot_time,
                        json.dumps(_json_safe(snapshot)),
                    )
                )

            if not rows:
                return 0

            cur.executemany(
                """
                INSERT INTO public.alpaca_option_snapshots
                  (underlying_symbol, option_symbol, snapshot_time, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (option_symbol, snapshot_time) DO UPDATE SET
                  underlying_symbol = EXCLUDED.underlying_symbol,
                  payload = EXCLUDED.payload
                """,
                rows,
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def main() -> int:
    underlying = str(get_env("UNDERLYING", "SPY")).strip().upper()
    feed = str(get_env("ALPACA_OPTIONS_FEED", "indicative")).strip().lower()
    max_pages = int(get_env("ALPACA_OPTIONS_MAX_PAGES", 3))
    max_pages = max(1, max_pages)

    snapshot_time = datetime.now(timezone.utc).replace(microsecond=0)

    snapshots, pages_used = fetch_option_snapshots(
        underlying=underlying,
        feed=feed,
        max_pages=max_pages,
    )

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.info(
            "options_snapshots_fetched",
            extra={
                "event_type": "options_snapshots_fetched",
                "mode": "api_only",
                "underlying": underlying,
                "snapshots": len(snapshots),
                "pages_used": pages_used,
                "snapshot_time": snapshot_time.isoformat(),
            },
        )
        return 0

    upserted = upsert_snapshots(
        db_url=db_url,
        snapshot_time=snapshot_time,
        underlying_symbol=underlying,
        snapshots=snapshots,
    )
    logger.info(
        "options_snapshots_upserted",
        extra={
            "event_type": "options_snapshots_upserted",
            "underlying": underlying,
            "snapshots": len(snapshots),
            "upserted": upserted,
            "pages_used": pages_used,
            "snapshot_time": snapshot_time.isoformat(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
