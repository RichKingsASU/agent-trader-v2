from __future__ import annotations

"""
Backfill options chain + greeks snapshots into Firestore (tenant-scoped).

Source:
  Alpaca Options Snapshots endpoint:
    GET https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}

Storage (warm):
  tenants/{TENANT_ID}/alpaca_option_snapshots/{docId}

Idempotency:
  Upserts are keyed by (contract_symbol, ts) via a stable Firestore doc id hash.
"""

import argparse
import hashlib
import logging
import os
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import requests

from backend.common.env import get_alpaca_key_id, get_alpaca_secret_key, get_env
from backend.common.logging import init_structured_logging
from backend.tenancy.paths import tenant_collection
from backend.time.nyse_time import is_trading_day, market_open_dt, parse_ts, to_nyse, to_utc, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillConfig:
    tenant_id: str
    underlyings: list[str]
    options_feed: str
    max_pages: int
    strike_window_pct: float
    dte_targets_days: list[int]
    last_trading_days: int | None
    require_bid_ask: bool


def parse_option_symbol(option_symbol: str) -> dict[str, Any] | None:
    """
    Parse OCC option symbol format.

    Format: SYMBOL[YY][MM][DD][C/P][STRIKE]
    Example: SPY241231C00550000
    """
    try:
        s = (option_symbol or "").strip().upper()
        if len(s) < 15:
            return None
        cp_index = -1
        for i, ch in enumerate(s):
            if ch in {"C", "P"}:
                cp_index = i
                break
        if cp_index == -1 or cp_index < 7:
            return None

        underlying = s[: cp_index - 6].strip()
        date_str = s[cp_index - 6 : cp_index]
        option_type = "call" if s[cp_index] == "C" else "put"
        strike_str = s[cp_index + 1 :]

        strike = int(strike_str) / 1000.0
        return {"underlying": underlying, "date": date_str, "type": option_type, "strike": strike}
    except Exception:
        return None


def _alpaca_headers() -> dict[str, str]:
    key = get_alpaca_key_id(required=True)
    secret = get_alpaca_secret_key(required=True)
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _stable_doc_id(*, contract_symbol: str, ts: datetime) -> str:
    # Keep doc ids compact/uniform; include ISO timestamp to preserve ordering semantics.
    key = f"{contract_symbol.strip().upper()}|{to_utc(ts).isoformat()}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:48]


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _extract_bid_ask(snapshot: dict[str, Any]) -> tuple[float | None, float | None]:
    # Alpaca payloads vary; handle common shapes:
    # - snapshot["latestQuote"]["bp"/"ap"] (bid/ask price)
    # - snapshot["latestQuote"]["bid_price"/"ask_price"]
    # - snapshot["quote"]["bp"/"ap"]
    q = snapshot.get("latestQuote") or snapshot.get("quote") or {}
    if not isinstance(q, dict):
        return None, None
    bid = _safe_float(q.get("bp") or q.get("bid_price") or q.get("bid"))
    ask = _safe_float(q.get("ap") or q.get("ask_price") or q.get("ask"))
    return bid, ask


def _extract_greeks(snapshot: dict[str, Any]) -> dict[str, float | None]:
    g = snapshot.get("greeks") or {}
    if not isinstance(g, dict):
        g = {}
    return {
        "delta": _safe_float(g.get("delta")),
        "gamma": _safe_float(g.get("gamma")),
        "theta": _safe_float(g.get("theta")),
        "vega": _safe_float(g.get("vega")),
    }


def _extract_ts(snapshot: dict[str, Any], *, fallback: datetime) -> datetime:
    """
    Prefer the provider timestamp embedded in the snapshot (latest quote/trade time).
    """
    candidates: list[Any] = []
    if isinstance(snapshot.get("latestQuote"), dict):
        candidates.extend(
            [
                snapshot["latestQuote"].get("t"),
                snapshot["latestQuote"].get("timestamp"),
                snapshot["latestQuote"].get("ts"),
            ]
        )
    if isinstance(snapshot.get("latestTrade"), dict):
        candidates.extend(
            [
                snapshot["latestTrade"].get("t"),
                snapshot["latestTrade"].get("timestamp"),
                snapshot["latestTrade"].get("ts"),
            ]
        )
    candidates.extend([snapshot.get("updated_at"), snapshot.get("timestamp"), snapshot.get("ts")])
    for c in candidates:
        if c is None:
            continue
        try:
            return parse_ts(c)
        except Exception:
            continue
    return to_utc(fallback)


def _fetch_underlying_price(*, symbol: str, headers: dict[str, str], stock_feed: str = "iex") -> float:
    """
    Fetch a best-effort underlying price (mid of bid/ask when present).
    """
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
    r = requests.get(url, headers=headers, params={"feed": stock_feed}, timeout=30)
    r.raise_for_status()
    data = r.json() or {}
    q = data.get("quote") or {}
    if isinstance(q, dict):
        bid = _safe_float(q.get("bp") or q.get("bid_price") or q.get("bid"))
        ask = _safe_float(q.get("ap") or q.get("ask_price") or q.get("ask"))
        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
            return float((bid + ask) / 2.0)

    # Fallback: latest trade price.
    turl = f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
    tr = requests.get(turl, headers=headers, params={"feed": stock_feed}, timeout=30)
    tr.raise_for_status()
    tdata = tr.json() or {}
    trade = tdata.get("trade") or {}
    if isinstance(trade, dict):
        price = _safe_float(trade.get("p") or trade.get("price"))
        if isinstance(price, (int, float)) and price > 0:
            return float(price)

    raise RuntimeError(f"Failed to fetch underlying price for {symbol} (missing quote + trade price)")


def fetch_option_snapshots_underlying(
    *,
    underlying: str,
    headers: dict[str, str],
    feed: str,
    max_pages: int,
) -> dict[str, Any]:
    url = f"https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}"
    page_token: str | None = None
    all_snaps: dict[str, Any] = {}
    pages_used = 0
    for _ in range(max_pages):
        params: dict[str, Any] = {"feed": feed}
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
    logger.info(
        "alpaca_snapshots_fetched underlying=%s snapshots=%s pages_used=%s",
        underlying,
        len(all_snaps),
        pages_used,
    )
    return all_snaps


def _pick_expirations(
    *,
    expirations: Iterable[date],
    today: date,
    dte_targets_days: list[int],
    max_dte_days: int,
) -> set[date]:
    eligible = []
    for d in expirations:
        dte = (d - today).days
        if dte < 0 or dte > max_dte_days:
            continue
        eligible.append((dte, d))
    if not eligible:
        return set()

    picked: set[date] = set()
    for target in dte_targets_days:
        best: tuple[int, date] | None = None
        best_dist = 10**9
        for dte, d in eligible:
            dist = abs(dte - target)
            if dist < best_dist:
                best_dist = dist
                best = (dte, d)
        if best is not None:
            picked.add(best[1])
    return picked


def _compute_min_ts_for_last_trading_days(n: int, *, now_utc: datetime) -> datetime:
    """
    Return the UTC market-open datetime for the oldest trading day in the lookback window.

    Example: n=1 -> today's market open (if today is a trading day), else most recent trading day open.
    """
    if n <= 0:
        raise ValueError("last_trading_days must be > 0")

    # Walk backwards over NY dates until we collect n trading days.
    cursor = to_nyse(now_utc).date()
    trading_days: list[date] = []
    while len(trading_days) < n:
        if is_trading_day(cursor):
            trading_days.append(cursor)
        cursor = cursor - timedelta(days=1)
    oldest = trading_days[-1]
    return to_utc(market_open_dt(oldest))


def _normalize_doc(
    *,
    tenant_id: str,
    underlying: str,
    contract_symbol: str,
    snapshot: dict[str, Any],
    underlying_price: float,
    ts: datetime,
    inserted_at: datetime,
) -> dict[str, Any] | None:
    parsed = parse_option_symbol(contract_symbol)
    if not parsed:
        return None

    # parsed["date"] is YYMMDD (string). Convert to ISO date.
    date_s = str(parsed.get("date") or "").strip()
    if len(date_s) != 6:
        return None
    yy = int(date_s[0:2])
    mm = int(date_s[2:4])
    dd = int(date_s[4:6])
    expiration = date(2000 + yy, mm, dd).isoformat()

    option_type = str(parsed.get("type") or "").lower()
    strike = _safe_float(parsed.get("strike"))
    if strike is None:
        return None

    bid, ask = _extract_bid_ask(snapshot)
    greeks = _extract_greeks(snapshot)

    # Keep a payload shape compatible with the UI hook (`useOptionsSnapshots`).
    payload: dict[str, Any] = {
        "expiration": expiration,
        "strike": float(strike),
        "option_type": option_type,
        "bid": bid,
        "ask": ask,
        "underlying_price": float(underlying_price),
        **greeks,
    }

    # Flatten a few fields for easier querying.
    doc: dict[str, Any] = {
        "tenant_id": tenant_id,
        "underlying_symbol": underlying,
        "option_symbol": contract_symbol,
        "contract_symbol": contract_symbol,  # alias requested in task
        "expiration": expiration,
        "strike": float(strike),
        "type": option_type,
        "bid": bid,
        "ask": ask,
        "underlying_price": float(underlying_price),
        "delta": greeks["delta"],
        "gamma": greeks["gamma"],
        "theta": greeks["theta"],
        "vega": greeks["vega"],
        "ts": to_utc(ts),
        "snapshot_time": to_utc(ts),  # what the UI queries on
        "inserted_at": to_utc(inserted_at),
        "source": "alpaca",
        "payload": payload,
    }
    return doc


def _write_docs_batch(
    *,
    tenant_id: str,
    docs: list[dict[str, Any]],
    project_id: str | None = None,
) -> int:
    from backend.persistence.firebase_client import get_firestore_client

    if not docs:
        return 0

    db = get_firestore_client(project_id=project_id)
    col = tenant_collection(db, tenant_id, "alpaca_option_snapshots")

    total = 0
    batch = db.batch()
    op_count = 0

    def commit() -> None:
        nonlocal batch, op_count, total
        if op_count == 0:
            return
        batch.commit()
        total += op_count
        batch = db.batch()
        op_count = 0

    for doc in docs:
        contract_symbol = str(doc.get("contract_symbol") or "").strip().upper()
        ts = doc.get("ts")
        if not contract_symbol or not isinstance(ts, datetime):
            continue
        doc_id = _stable_doc_id(contract_symbol=contract_symbol, ts=ts)
        ref = col.document(doc_id)
        batch.set(ref, doc, merge=True)
        op_count += 1
        if op_count >= 450:
            commit()

    commit()
    return total


def _parse_csv(s: str) -> list[str]:
    out: list[str] = []
    for part in (s or "").split(","):
        p = part.strip().upper()
        if p:
            out.append(p)
    return out


def _load_config() -> BackfillConfig:
    tenant_id = str(get_env("TENANT_ID", "local")).strip() or "local"
    underlyings = _parse_csv(str(get_env("UNDERLYINGS", "SPY,QQQ,IWM,AAPL,TSLA")))
    options_feed = str(get_env("ALPACA_OPTIONS_FEED", "indicative")).strip().lower()
    max_pages = int(get_env("ALPACA_OPTIONS_MAX_PAGES", 20))
    max_pages = max(1, max_pages)
    strike_window_pct = float(get_env("OPTION_STRIKE_WINDOW_PCT", 10.0)) / 100.0
    strike_window_pct = max(0.0, strike_window_pct)
    dte_targets_days = [7, 14, 30]
    last_trading_days_env = str(os.getenv("LAST_TRADING_DAYS") or "").strip()
    last_trading_days = int(last_trading_days_env) if last_trading_days_env else None
    require_bid_ask = str(get_env("REQUIRE_BID_ASK", "true")).strip().lower() in {"1", "true", "yes", "y", "on"}
    return BackfillConfig(
        tenant_id=tenant_id,
        underlyings=underlyings,
        options_feed=options_feed,
        max_pages=max_pages,
        strike_window_pct=strike_window_pct,
        dte_targets_days=dte_targets_days,
        last_trading_days=last_trading_days,
        require_bid_ask=require_bid_ask,
    )


def main(argv: list[str] | None = None) -> int:
    init_structured_logging(service="alpaca-options-snapshots-backfill-firestore")

    parser = argparse.ArgumentParser(description="Backfill Alpaca option snapshots into Firestore.")
    parser.add_argument("--tenant-id", default=None, help="Tenant id (default: env TENANT_ID or 'local').")
    parser.add_argument(
        "--underlyings",
        default=None,
        help="Comma-separated underlyings (default: env UNDERLYINGS or SPY,QQQ,IWM,AAPL,TSLA).",
    )
    parser.add_argument("--options-feed", default=None, help="Options feed: indicative|opra (default env ALPACA_OPTIONS_FEED).")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages for snapshots/{underlying} pagination.")
    parser.add_argument("--strike-window-pct", type=float, default=None, help="ATM window percent (default 10).")
    parser.add_argument("--last-trading-days", type=int, default=None, help="Filter to snapshots with ts in last N trading days.")
    parser.add_argument("--allow-missing-bid-ask", action="store_true", help="Do not require bid/ask to be present/positive.")

    args = parser.parse_args(argv)

    cfg = _load_config()
    if args.tenant_id:
        cfg = replace(cfg, tenant_id=str(args.tenant_id).strip())
    if args.underlyings:
        cfg = replace(cfg, underlyings=_parse_csv(args.underlyings))
    if args.options_feed:
        cfg = replace(cfg, options_feed=str(args.options_feed).strip().lower())
    if args.max_pages is not None:
        cfg = replace(cfg, max_pages=max(1, int(args.max_pages)))
    if args.strike_window_pct is not None:
        cfg = replace(cfg, strike_window_pct=max(0.0, float(args.strike_window_pct) / 100.0))
    if args.last_trading_days is not None:
        cfg = replace(cfg, last_trading_days=max(1, int(args.last_trading_days)))
    if args.allow_missing_bid_ask:
        cfg = replace(cfg, require_bid_ask=False)

    if not cfg.underlyings:
        logger.error("No underlyings configured")
        return 2

    headers = _alpaca_headers()
    inserted_at = utc_now().replace(microsecond=0)
    stock_feed = str(os.getenv("ALPACA_STOCK_FEED") or "iex").strip().lower() or "iex"

    min_ts: datetime | None = None
    if cfg.last_trading_days:
        min_ts = _compute_min_ts_for_last_trading_days(cfg.last_trading_days, now_utc=inserted_at)
        logger.info("ts_filter_enabled last_trading_days=%s min_ts=%s", cfg.last_trading_days, min_ts.isoformat())

    total_written = 0
    for underlying in cfg.underlyings:
        try:
            underlying_price = _fetch_underlying_price(symbol=underlying, headers=headers, stock_feed=stock_feed)
            snaps = fetch_option_snapshots_underlying(
                underlying=underlying,
                headers=headers,
                feed=cfg.options_feed,
                max_pages=cfg.max_pages,
            )

            # First pass: parse expirations (within 30D) so we can pick the closest to 7/14/30 DTE.
            today = inserted_at.date()
            expirations: set[date] = set()
            parsed_cache: dict[str, dict[str, Any]] = {}
            for opt_sym in snaps.keys():
                parsed = parse_option_symbol(opt_sym)
                if not parsed:
                    continue
                parsed_cache[opt_sym] = parsed
                date_s = str(parsed.get("date") or "").strip()
                if len(date_s) != 6:
                    continue
                yy = int(date_s[0:2])
                mm = int(date_s[2:4])
                dd = int(date_s[4:6])
                exp = date(2000 + yy, mm, dd)
                dte = (exp - today).days
                if 0 <= dte <= 30:
                    expirations.add(exp)

            picked = _pick_expirations(
                expirations=expirations,
                today=today,
                dte_targets_days=cfg.dte_targets_days,
                max_dte_days=30,
            )

            if not picked:
                logger.warning("%s: no expirations found within 30D in fetched pages", underlying)

            # Second pass: normalize + filter by strike window and picked expirations.
            strike_min = underlying_price * (1.0 - cfg.strike_window_pct)
            strike_max = underlying_price * (1.0 + cfg.strike_window_pct)

            docs: list[dict[str, Any]] = []
            filtered = 0
            for opt_sym, snap in snaps.items():
                if not isinstance(snap, dict):
                    continue

                parsed = parsed_cache.get(opt_sym) or parse_option_symbol(opt_sym)
                if not parsed:
                    continue

                # Expiration filter (picked expirations near 7/14/30D).
                date_s = str(parsed.get("date") or "").strip()
                if len(date_s) != 6:
                    continue
                yy = int(date_s[0:2])
                mm = int(date_s[2:4])
                dd = int(date_s[4:6])
                exp_d = date(2000 + yy, mm, dd)
                if picked and exp_d not in picked:
                    filtered += 1
                    continue

                # Strike window filter (+/- 10% by default).
                strike = _safe_float(parsed.get("strike"))
                if strike is None or strike < strike_min or strike > strike_max:
                    filtered += 1
                    continue

                bid, ask = _extract_bid_ask(snap)
                if cfg.require_bid_ask:
                    if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0):
                        filtered += 1
                        continue

                ts = _extract_ts(snap, fallback=inserted_at).replace(microsecond=0)
                if min_ts and to_utc(ts) < to_utc(min_ts):
                    filtered += 1
                    continue

                doc = _normalize_doc(
                    tenant_id=cfg.tenant_id,
                    underlying=underlying,
                    contract_symbol=str(opt_sym).strip().upper(),
                    snapshot=snap,
                    underlying_price=underlying_price,
                    ts=ts,
                    inserted_at=inserted_at,
                )
                if doc:
                    docs.append(doc)

            written = _write_docs_batch(tenant_id=cfg.tenant_id, docs=docs)
            total_written += written

            logger.info(
                "underlying_done underlying=%s underlying_price=%.4f expirations_picked=%s docs=%s written=%s filtered=%s",
                underlying,
                float(underlying_price),
                sorted([d.isoformat() for d in picked]),
                len(docs),
                written,
                filtered,
            )
        except Exception as e:
            logger.exception("underlying_failed underlying=%s err=%s", underlying, e)

    if total_written == 0:
        logger.error("No documents written (check Alpaca access, filters, and Firestore credentials)")
        return 1

    logger.info("done tenant_id=%s total_written=%s", cfg.tenant_id, total_written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

