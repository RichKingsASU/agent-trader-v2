from __future__ import annotations

"""
Alpaca options chain snapshot ingestion (import-safe).

Test contract (see `tests/test_ingest.py`):
- module must be importable without env credentials
- expose `main`, `fetch_option_snapshots`, and `upsert_snapshots`
- `fetch_option_snapshots` must paginate using `next_page_token`
- `upsert_snapshots` must execute an UPSERT into `public.alpaca_option_snapshots`
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Tuple

import requests


def _required_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v).strip()


def _alpaca_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": _required_env("APCA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": _required_env("APCA_API_SECRET_KEY"),
    }


def fetch_option_snapshots(
    *,
    underlying: str,
    feed: str = "indicative",
    max_pages: int = 3,
    timeout_s: float = 5.0,
) -> tuple[dict[str, Any], int]:
    """
    Fetch option snapshots for an underlying symbol with simple pagination.

    Returns (snapshots_by_option_symbol, pages_fetched).
    """
    base_url = (os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets").rstrip("/")
    url = f"{base_url}/v2/options/snapshots/{str(underlying).strip().upper()}"

    out: dict[str, Any] = {}
    page_token: str | None = None
    pages = 0

    for _ in range(max(1, int(max_pages))):
        params = {"feed": str(feed).strip().lower() or "indicative"}
        if page_token:
            params["page_token"] = page_token

        r = requests.get(url, headers=_alpaca_headers(), params=params, timeout=max(0.1, float(timeout_s)))
        r.raise_for_status()
        data = r.json() or {}

        snaps = data.get("snapshots")
        if isinstance(snaps, Mapping):
            for k, v in snaps.items():
                if k is None:
                    continue
                out[str(k)] = v

        pages += 1
        next_tok = data.get("next_page_token")
        page_token = str(next_tok).strip() if next_tok is not None and str(next_tok).strip() else None
        if not page_token:
            break

    return out, pages


def _connect_db(db_url: str):
    """
    Connect to Postgres.

    NOTE: tests monkeypatch this function; keep the import local.
    """
    import psycopg  # type: ignore

    return "psycopg", psycopg.connect(db_url)


def upsert_snapshots(
    *,
    db_url: str,
    snapshot_time: datetime,
    underlying_symbol: str,
    snapshots: Mapping[str, Any],
) -> int:
    """
    Upsert snapshots into `public.alpaca_option_snapshots`.
    """
    if snapshot_time.tzinfo is None:
        snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)
    snapshot_time = snapshot_time.astimezone(timezone.utc)

    _driver, conn = _connect_db(db_url)
    rows: list[tuple[Any, ...]] = []
    for opt_symbol, payload in snapshots.items():
        rows.append(
            (
                snapshot_time,
                str(underlying_symbol).strip().upper(),
                str(opt_symbol).strip().upper(),
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            )
        )

    sql = """
    INSERT INTO public.alpaca_option_snapshots
      (snapshot_time_utc, underlying_symbol, option_symbol, snapshot_json)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (snapshot_time_utc, option_symbol)
    DO UPDATE SET
      underlying_symbol = EXCLUDED.underlying_symbol,
      snapshot_json = EXCLUDED.snapshot_json
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def main() -> int:
    """
    Minimal CLI entrypoint.
    """
    underlying = os.getenv("ALPACA_UNDERLYING") or "SPY"
    feed = os.getenv("ALPACA_OPTIONS_FEED") or "indicative"
    max_pages = int(os.getenv("ALPACA_OPTIONS_MAX_PAGES") or "3")
    db_url = os.getenv("DATABASE_URL") or ""
    if not db_url.strip():
        raise RuntimeError("Missing required env var: DATABASE_URL")
    snapshot_time = datetime.now(timezone.utc)

    snaps, _pages = fetch_option_snapshots(underlying=underlying, feed=feed, max_pages=max_pages)
    upsert_snapshots(db_url=db_url, snapshot_time=snapshot_time, underlying_symbol=underlying, snapshots=snaps)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

