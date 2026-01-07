"""backend/streams/alpaca_option_window_ingest.py

Ingest a small "window" of Alpaca option snapshots around ATM.

Filters:
- Underlyings: env ALPACA_SYMBOLS (default: SPY,IWM,QQQ)
- Expirations: DTE 0..OPTION_DTE_MAX calendar days (default: 5)
- Strikes: within ±OPTION_STRIKE_WINDOW dollars of ATM per-expiration (default: 5)
- Include both calls and puts

Writes:
- Upsert into public.alpaca_option_snapshots
  (underlying_symbol, option_symbol, snapshot_time, payload, inserted_at)
  - payload stores the full snapshot JSON
  - inserted_at is written if the column exists (some DBs may omit it)

Fail-fast:
- If total upserts == 0, exit non-zero.

Env required:
- ALPACA_KEY_ID, ALPACA_SECRET_KEY
- DATABASE_URL

Env read:
- ALPACA_SYMBOLS, OPTION_DTE_MAX, OPTION_STRIKE_WINDOW, ALPACA_FEED, ALPACA_PAPER, DATABASE_URL

Notes:
- Uses Alpaca options contracts endpoint to discover symbols, then requests snapshots for those option symbols.
- Strike increment is inferred from available strikes for each expiration; falls back to 1.0.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

# Task requirements: contracts from trading base; snapshots from Alpaca data host.
TRADING_BASE = (
    "https://paper-api.alpaca.markets"
    if str(os.getenv("ALPACA_PAPER", "true")).lower() == "true"
    else "https://api.alpaca.markets"
)
DATA_BASE = "https://data.alpaca.markets"

from backend.common.agent_boot import configure_startup_logging
from backend.common.env import get_env

# Keep consistent with other backend/streams scripts
from backend.streams.alpaca_env import load_alpaca_env


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowConfig:
    symbols: List[str]
    dte_max: int
    strike_window: float
    options_feed: str
    alpaca_paper: Optional[bool]


def _json_safe(v: Any) -> Any:
    """Convert nested objects to JSON-safe primitives."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    return str(v)


def _parse_csv_symbols(s: str) -> List[str]:
    out: List[str] = []
    for part in (s or "").split(","):
        p = part.strip().upper()
        if p:
            out.append(p)
    return out


def _parse_bool(s: Optional[str]) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return None


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _headers(key: str, secret: str) -> Dict[str, str]:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _request_json(
    url: str,
    *,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    timeout_s: int = 30,
) -> Dict[str, Any]:
    r = requests.get(url, headers=headers, params=params or {}, timeout=timeout_s)
    r.raise_for_status()
    return r.json() or {}


def fetch_underlying_latest_price(
    *,
    data_host: str,
    headers: Dict[str, str],
    symbol: str,
    stock_feed: Optional[str],
) -> float:
    """Best-effort latest underlying price via v2 stocks latest trade/quote."""

    # Prefer latest trade
    trade_url = f"{data_host.rstrip('/')}/v2/stocks/{symbol}/trades/latest"
    trade_params: Dict[str, Any] = {}
    if stock_feed:
        trade_params["feed"] = stock_feed

    try:
        payload = _request_json(trade_url, headers=headers, params=trade_params)
        trade = payload.get("trade") or {}
        p = _num(trade.get("p") or trade.get("price"))
        if p is not None and p > 0:
            return p
    except Exception:
        # fall back to quote
        pass

    quote_url = f"{data_host.rstrip('/')}/v2/stocks/{symbol}/quotes/latest"
    quote_params: Dict[str, Any] = {}
    if stock_feed:
        quote_params["feed"] = stock_feed

    payload = _request_json(quote_url, headers=headers, params=quote_params)
    quote = payload.get("quote") or {}
    bid = _num(quote.get("bp") or quote.get("bid_price") or quote.get("bidPrice"))
    ask = _num(quote.get("ap") or quote.get("ask_price") or quote.get("askPrice"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0

    # Last resort: try "last" (some feeds may return different keys)
    last = _num(payload.get("last"))
    if last is not None and last > 0:
        return last

    raise RuntimeError(f"Unable to determine latest price for {symbol}")


def fetch_option_contracts(
    *,
    trading_host: str,
    headers: Dict[str, str],
    underlying: str,
    exp_gte: date,
    exp_lte: date,
    limit: int = 10000,
    max_pages: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch option contracts for an underlying within expiration date window."""

    # Task requirement: fetch contracts from TRADING_BASE using /v2/options/contracts
    url = f"{trading_host.rstrip('/')}/v2/options/contracts"

    page_token: Optional[str] = None
    all_contracts: List[Dict[str, Any]] = []

    for _ in range(max_pages):
        params: Dict[str, Any] = {
            "underlying_symbols": underlying,
            "expiration_date_gte": exp_gte.isoformat(),
            "expiration_date_lte": exp_lte.isoformat(),
            "limit": limit,
        }
        if page_token:
            params["page_token"] = page_token

        payload = _request_json(url, headers=headers, params=params)

        contracts = (
            payload.get("option_contracts")
            or payload.get("contracts")
            or payload.get("results")
            or []
        )
        if isinstance(contracts, list):
            all_contracts.extend([c for c in contracts if isinstance(c, dict)])

        page_token = payload.get("next_page_token") or payload.get("next_page_token".upper())
        if not page_token:
            break

    return all_contracts


def _get_expiration_date(contract: Dict[str, Any]) -> Optional[date]:
    v = contract.get("expiration_date") or contract.get("expirationDate") or contract.get("expiration")
    if not v:
        return None
    try:
        # Expect YYYY-MM-DD
        return date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _get_strike(contract: Dict[str, Any]) -> Optional[float]:
    v = contract.get("strike_price") or contract.get("strike") or contract.get("strikePrice")
    return _num(v)


def _get_option_symbol(contract: Dict[str, Any]) -> Optional[str]:
    v = contract.get("symbol") or contract.get("option_symbol") or contract.get("id")
    if not v:
        return None
    s = str(v).strip().upper()
    return s or None


def infer_strike_increment(strikes: Sequence[float]) -> float:
    uniq = sorted({round(float(s), 6) for s in strikes if s is not None})
    if len(uniq) < 2:
        return 1.0
    diffs = [b - a for a, b in zip(uniq, uniq[1:]) if (b - a) > 1e-9]
    if not diffs:
        return 1.0
    inc = min(diffs)
    if inc <= 0:
        return 1.0
    # Avoid pathological tiny increments from float noise
    return float(round(inc, 6))


def choose_atm_strike(underlying_price: float, strikes: Sequence[float]) -> float:
    if not strikes:
        return float(round(underlying_price))
    return min(strikes, key=lambda s: abs(s - underlying_price))


def select_option_symbols_window(
    *,
    underlying: str,
    underlying_price: float,
    contracts: Sequence[Dict[str, Any]],
    dte_max: int,
    strike_window: float,
) -> Tuple[List[str], Dict[str, Any]]:
    """Return selected option symbols and per-underlying stats."""

    today = _today_utc()

    # Strict filters:
    # - DTE 0..dte_max inclusive
    # - strikes within ±strike_window of *current underlying price*
    # - include both calls and puts (no type filter)
    contracts_after_dte = 0
    contracts_after_strike = 0

    # Group contracts by expiration date within DTE window
    by_exp: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for c in contracts:
        exp = _get_expiration_date(c)
        if not exp:
            continue
        dte = (exp - today).days
        if 0 <= dte <= dte_max:
            contracts_after_dte += 1
            by_exp[exp].append(c)

    expirations = sorted(by_exp.keys())

    selected_symbols: List[str] = []
    per_exp_details: Dict[str, Any] = {}

    for exp in expirations:
        cs = by_exp[exp]
        strikes = [s for s in (_get_strike(c) for c in cs) if s is not None]
        if not strikes:
            continue

        inc = infer_strike_increment(strikes)
        lo = float(underlying_price) - float(strike_window)
        hi = float(underlying_price) + float(strike_window)

        kept: List[str] = []
        for c in cs:
            strike = _get_strike(c)
            if strike is None:
                continue
            if lo <= strike <= hi:
                contracts_after_strike += 1
                sym = _get_option_symbol(c)
                if sym:
                    kept.append(sym)

        # De-dupe while preserving order
        seen: set[str] = set()
        kept = [s for s in kept if not (s in seen or seen.add(s))]

        selected_symbols.extend(kept)
        per_exp_details[exp.isoformat()] = {
            "contracts": len(cs),
            "selected": len(kept),
            "strike_increment": inc,
            "strike_range": [lo, hi],
        }

    # De-dupe overall
    seen_all: set[str] = set()
    selected_symbols = [s for s in selected_symbols if not (s in seen_all or seen_all.add(s))]

    stats = {
        "underlying": underlying,
        "underlying_price": underlying_price,
        "expirations_found": len(expirations),
        "contracts_scanned": len(contracts),
        "contracts_after_dte": contracts_after_dte,
        "contracts_after_strike": contracts_after_strike,
        "contracts_selected": len(selected_symbols),
        "per_exp": per_exp_details,
    }

    return selected_symbols, stats


def fetch_option_snapshots_for_symbols(
    *,
    headers: Dict[str, str],
    option_symbols: Sequence[str],
) -> Dict[str, Any]:
    """Fetch option snapshots by contract symbols, chunking requests."""

    if not option_symbols:
        return {}

    all_snapshots: Dict[str, Any] = {}
    
    # Alpaca API has a limit of 200 symbols per request
    chunk_size = 200
    
    symbols_to_fetch = sorted(list(set(str(s).strip().upper() for s in option_symbols if s)))

    for i in range(0, len(symbols_to_fetch), chunk_size):
        chunk = symbols_to_fetch[i:i + chunk_size]
        
        logger.info(f"Requesting snapshots for {len(chunk)} option symbols...")

        # Task requirement: fetch snapshots from this endpoint with symbols query param.
        url = f"{DATA_BASE.rstrip('/')}/v1beta1/options/snapshots"
        params = {"symbols": ",".join(chunk)}
        
        try:
            payload = _request_json(url, headers=headers, params=params)
            
            snaps: Any = payload.get("snapshots")
            if snaps is None:
                snaps = payload
            if not isinstance(snaps, dict):
                logger.warning(f"Received non-dict snapshots payload: {snaps}")
                continue

            logger.info(f"Received {len(snaps)} snapshots in this chunk.")
            all_snapshots.update(snaps)

        except Exception as e:
            logger.exception(f"Failed to fetch snapshot chunk: {e}")

    logger.info(f"Total snapshots received: {len(all_snapshots)}")
    return all_snapshots


def _connect_db(db_url: str):
    """Prefer psycopg (v3) if available, fall back to psycopg2."""
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
                "Install one (e.g. pip install psycopg[binary]) to enable DB writes."
            ) from e


def _db_has_inserted_at(conn) -> bool:
    """Return True if public.alpaca_option_snapshots.inserted_at exists."""
    q = """
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'alpaca_option_snapshots'
      and column_name = 'inserted_at'
    limit 1
    """
    with conn.cursor() as cur:
        cur.execute(q)
        return cur.fetchone() is not None


def upsert_snapshots(
    *,
    db_url: str,
    snapshot_time: datetime,
    inserted_at: datetime,
    underlying_symbol: str,
    snapshots: Dict[str, Any],
) -> int:
    """Upsert snapshots into public.alpaca_option_snapshots."""

    _, conn = _connect_db(db_url)
    try:
        has_inserted_at = _db_has_inserted_at(conn)

        rows: List[Tuple[Any, ...]] = []
        for option_symbol, snapshot in (snapshots or {}).items():
            if not option_symbol:
                continue
            rows.append(
                (
                    underlying_symbol,
                    str(option_symbol).strip().upper(),
                    snapshot_time,
                    json.dumps(_json_safe(snapshot)),
                    inserted_at,
                )
            )

        if not rows:
            return 0

        with conn.cursor() as cur:
            if has_inserted_at:
                cur.executemany(
                    """
                    insert into public.alpaca_option_snapshots
                      (underlying_symbol, option_symbol, snapshot_time, payload, inserted_at)
                    values (%s, %s, %s, %s::jsonb, %s)
                    on conflict (option_symbol, snapshot_time) do update set
                      underlying_symbol = excluded.underlying_symbol,
                      payload = excluded.payload,
                      inserted_at = excluded.inserted_at
                    """,
                    rows,
                )
            else:
                # Drop inserted_at (5th element)
                rows4 = [(a, b, c, d) for (a, b, c, d, _e) in rows]
                cur.executemany(
                    """
                    insert into public.alpaca_option_snapshots
                      (underlying_symbol, option_symbol, snapshot_time, payload)
                    values (%s, %s, %s, %s::jsonb)
                    on conflict (option_symbol, snapshot_time) do update set
                      underlying_symbol = excluded.underlying_symbol,
                      payload = excluded.payload
                    """,
                    rows4,
                )

        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_config() -> WindowConfig:
    symbols = _parse_csv_symbols(str(get_env("ALPACA_SYMBOLS", "SPY,IWM,QQQ")))
    dte_max = int(get_env("OPTION_DTE_MAX", 5))
    dte_max = max(0, dte_max)
    strike_window = float(get_env("OPTION_STRIKE_WINDOW", 5))
    strike_window = max(0.0, strike_window)

    # Alpaca options feed (e.g., 'indicative' or 'opra').
    options_feed = str(get_env("ALPACA_FEED", "indicative")).strip().lower()

    alpaca_paper = _parse_bool(os.getenv("ALPACA_PAPER"))

    return WindowConfig(
        symbols=symbols,
        dte_max=dte_max,
        strike_window=strike_window,
        options_feed=options_feed,
        alpaca_paper=alpaca_paper,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    configure_startup_logging(
        agent_name="options-window-ingest",
        intent="Ingest an option snapshot window around ATM and upsert to Postgres.",
    )

    cfg = load_config()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is required")
        return 2

    alpaca = load_alpaca_env(require_keys=True)
    hdrs = _headers(alpaca.key_id, alpaca.secret_key)

    # Use ALPACA_FEED as a stock feed only if it looks like one; otherwise omit.
    stock_feed: Optional[str] = None
    if cfg.options_feed in {"iex", "sip"}:
        stock_feed = cfg.options_feed
    else:
        stock_feed = os.getenv("ALPACA_STOCK_FEED", "iex").strip().lower() if os.getenv("ALPACA_STOCK_FEED") else "iex"

    today = _today_utc()

    snapshot_time = datetime.now(timezone.utc).replace(microsecond=0)
    inserted_at = snapshot_time

    logger.info(
        "Starting alpaca_option_window_ingest symbols=%s dte_max=%s strike_window=%s options_feed=%s alpaca_paper=%s",
        ",".join(cfg.symbols),
        cfg.dte_max,
        cfg.strike_window,
        cfg.options_feed,
        cfg.alpaca_paper,
    )

    total_expirations = 0
    total_contracts_selected = 0
    total_snapshots_fetched = 0
    total_rows_upserted = 0

    for underlying in cfg.symbols:
        try:
            strict = underlying in {"SPY", "IWM", "QQQ"}
            dte_max = 5 if strict else cfg.dte_max
            strike_window = 5.0 if strict else cfg.strike_window
            exp_lte = today + timedelta(days=dte_max)

            underlying_price = fetch_underlying_latest_price(
                data_host=alpaca.data_host,
                headers=hdrs,
                symbol=underlying,
                stock_feed=stock_feed,
            )

            contracts = fetch_option_contracts(
                trading_host=TRADING_BASE,
                headers=hdrs,
                underlying=underlying,
                exp_gte=today,
                exp_lte=exp_lte,
            )

            option_symbols, stats = select_option_symbols_window(
                underlying=underlying,
                underlying_price=underlying_price,
                contracts=contracts,
                dte_max=dte_max,
                strike_window=strike_window,
            )

            expirations_found = int(stats.get("expirations_found") or 0)
            contracts_selected = int(stats.get("contracts_selected") or 0)
            contracts_after_dte = int(stats.get("contracts_after_dte") or 0)
            contracts_after_strike = int(stats.get("contracts_after_strike") or 0)

            logger.info(
                "%s: total_contracts_found=%s total_after_dte_filter=%s total_after_strike_filter=%s",
                underlying,
                len(contracts),
                contracts_after_dte,
                contracts_after_strike,
            )

            snapshots = fetch_option_snapshots_for_symbols(
                headers=hdrs,
                option_symbols=option_symbols,
            )

            fetched = len(snapshots)
            upserted = upsert_snapshots(
                db_url=db_url,
                snapshot_time=snapshot_time,
                inserted_at=inserted_at,
                underlying_symbol=underlying,
                snapshots=snapshots,
            )
            logger.info("%s: snapshots_found=%s rows_upserted=%s", underlying, fetched, upserted)

            total_expirations += expirations_found
            total_contracts_selected += contracts_selected
            total_snapshots_fetched += fetched
            total_rows_upserted += upserted

            logger.info(
                "%s: expirations_found=%s contracts_selected=%s snapshots_fetched=%s rows_upserted=%s underlying_price=%.4f",
                underlying,
                expirations_found,
                contracts_selected,
                fetched,
                upserted,
                underlying_price,
            )

        except Exception as e:
            logger.exception("%s: failed: %s", underlying, e)

    logger.info(
        "Done: total_expirations_found=%s total_contracts_selected=%s total_snapshots_fetched=%s total_rows_upserted=%s snapshot_time=%s",
        total_expirations,
        total_contracts_selected,
        total_snapshots_fetched,
        total_rows_upserted,
        snapshot_time.isoformat(),
    )

    if total_rows_upserted == 0:
        logger.error("Fail-fast: total upserts == 0")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
