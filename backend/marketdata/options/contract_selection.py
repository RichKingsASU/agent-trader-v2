"""
Deterministic SPY option contract selection (scalper).

Rules implemented:
- Uses Alpaca **option snapshots** (read-only) for liquidity ranking
- 0–1 DTE only (calendar DTE computed using America/New_York date)
- Nearest ATM (minimum |strike - underlying_price|)
- Highest liquidity (tightest spread, then deepest quotes, then vol/OI)
- Single-leg only

This module is intentionally dependency-light:
- No broker SDK imports
- No DB/Firestore writes
- Uses `requests` for Alpaca GETs only
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

import requests

from backend.streams.alpaca_env import load_alpaca_env
from backend.time.nyse_time import to_nyse, utc_now

OptionRight = Literal["call", "put"]


def _headers(*, key_id: str, secret_key: str) -> Dict[str, str]:
    return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in mapping and mapping.get(k) is not None:
            return mapping.get(k)
    return None


def _get_nested(obj: Any, path: Sequence[str]) -> Any:
    cur: Any = obj
    for k in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(k)
    return cur


def _parse_iso_date(d: Any) -> Optional[date]:
    if d is None:
        return None
    s = str(d).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class OptionContract:
    symbol: str
    expiration: date
    right: OptionRight
    strike: float

    @property
    def occ_symbol(self) -> str:
        return self.symbol


@dataclass(frozen=True, slots=True)
class OptionSnapshotView:
    contract_symbol: str
    snapshot_time: Optional[str]

    bid: Optional[float]
    ask: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]
    last: Optional[float]

    volume: Optional[float]
    open_interest: Optional[float]
    implied_volatility: Optional[float]

    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0:
            return None
        if self.ask < self.bid:
            return None
        return self.ask - self.bid

    @property
    def spread_pct(self) -> Optional[float]:
        m = self.mid
        s = self.spread
        if m is None or s is None or m <= 0:
            return None
        return s / m

    @property
    def min_quote_size(self) -> Optional[float]:
        if self.bid_size is None or self.ask_size is None:
            return None
        return float(min(self.bid_size, self.ask_size))


def fetch_underlying_latest_price(
    *,
    data_host: str,
    headers: Dict[str, str],
    symbol: str,
    stock_feed: Optional[str] = None,
    timeout_s: float = 10.0,
) -> float:
    """
    Best-effort underlying mid via latest trade -> latest quote.
    """
    base = data_host.rstrip("/")

    trade_url = f"{base}/v2/stocks/{symbol}/trades/latest"
    trade_params: Dict[str, Any] = {}
    if stock_feed:
        trade_params["feed"] = stock_feed
    r = requests.get(trade_url, headers=headers, params=trade_params, timeout=timeout_s)
    if r.status_code == 200:
        payload = r.json() or {}
        trade = payload.get("trade") or {}
        p = _num(trade.get("p") or trade.get("price"))
        if p is not None and p > 0:
            return p

    quote_url = f"{base}/v2/stocks/{symbol}/quotes/latest"
    quote_params: Dict[str, Any] = {}
    if stock_feed:
        quote_params["feed"] = stock_feed
    r2 = requests.get(quote_url, headers=headers, params=quote_params, timeout=timeout_s)
    r2.raise_for_status()
    payload2 = r2.json() or {}
    quote = payload2.get("quote") or {}
    bid = _num(quote.get("bp") or quote.get("bid_price") or quote.get("bidPrice"))
    ask = _num(quote.get("ap") or quote.get("ask_price") or quote.get("askPrice"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0

    raise RuntimeError(f"Unable to determine latest price for {symbol}")


def fetch_option_contracts(
    *,
    trading_host: str,
    headers: Dict[str, str],
    underlying: str,
    expiration_gte: date,
    expiration_lte: date,
    limit: int = 10000,
    max_pages: int = 50,
    timeout_s: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Fetch Alpaca option contracts (read-only).

    Endpoint: GET {trading_host}/v2/options/contracts
    """
    base = trading_host.rstrip("/")
    url = f"{base}/v2/options/contracts"
    page_token: Optional[str] = None
    out: List[Dict[str, Any]] = []

    for _ in range(max_pages):
        params: Dict[str, Any] = {
            "underlying_symbols": str(underlying).strip().upper(),
            "expiration_date_gte": expiration_gte.isoformat(),
            "expiration_date_lte": expiration_lte.isoformat(),
            "limit": int(limit),
        }
        if page_token:
            params["page_token"] = page_token
        r = requests.get(url, headers=headers, params=params, timeout=timeout_s)
        r.raise_for_status()
        payload = r.json() or {}
        contracts = payload.get("option_contracts") or payload.get("contracts") or payload.get("results") or []
        if isinstance(contracts, list):
            out.extend([c for c in contracts if isinstance(c, dict)])
        page_token = payload.get("next_page_token") or payload.get("next_page_token".upper())
        if not page_token:
            break
    return out


def _contract_from_api(obj: Mapping[str, Any]) -> Optional[OptionContract]:
    sym = str(_first(obj, "symbol", "option_symbol", "id") or "").strip().upper()
    if not sym:
        return None
    exp = _parse_iso_date(_first(obj, "expiration_date", "expirationDate", "expiration"))
    if exp is None:
        return None
    strike = _num(_first(obj, "strike_price", "strikePrice", "strike"))
    if strike is None:
        return None
    typ = str(_first(obj, "type", "option_type", "right") or "").strip().lower()
    if typ in {"call", "c"}:
        right: OptionRight = "call"
    elif typ in {"put", "p"}:
        right = "put"
    else:
        return None
    return OptionContract(symbol=sym, expiration=exp, right=right, strike=float(strike))


def fetch_option_snapshots(
    *,
    data_host: str,
    headers: Dict[str, str],
    contract_symbols: Sequence[str],
    options_feed: Optional[str] = None,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    """
    Fetch Alpaca option snapshots (read-only).

    Endpoint: GET {data_host}/v1beta1/options/snapshots?symbols=...
    """
    syms = sorted({str(s).strip().upper() for s in contract_symbols if str(s).strip()})
    if not syms:
        return {}
    base = data_host.rstrip("/")
    url = f"{base}/v1beta1/options/snapshots"

    # Alpaca limit is ~200 symbols per request.
    chunk = 200
    out: Dict[str, Any] = {}
    for i in range(0, len(syms), chunk):
        part = syms[i : i + chunk]
        params: Dict[str, Any] = {"symbols": ",".join(part)}
        if options_feed:
            params["feed"] = str(options_feed).strip().lower()
        r = requests.get(url, headers=headers, params=params, timeout=timeout_s)
        r.raise_for_status()
        payload = r.json() or {}
        snaps: Any = payload.get("snapshots")
        if snaps is None:
            snaps = payload
        if isinstance(snaps, Mapping):
            for k, v in snaps.items():
                if isinstance(v, Mapping):
                    out[str(k).strip().upper()] = dict(v)
    return out


def _snapshot_view(contract_symbol: str, snapshot: Mapping[str, Any]) -> OptionSnapshotView:
    # Quote/trade shapes vary by API version; extract robustly.
    q = snapshot.get("latestQuote") or snapshot.get("latest_quote") or snapshot.get("quote") or {}
    t = snapshot.get("latestTrade") or snapshot.get("latest_trade") or snapshot.get("trade") or {}
    greeks = snapshot.get("greeks") or {}

    # Snapshot time: prefer quote time, else trade time, else top-level.
    snap_ts = (
        _first(q, "t", "timestamp")
        or _first(t, "t", "timestamp")
        or _first(snapshot, "timestamp", "t")
    )
    snap_ts_s = str(snap_ts).strip() if snap_ts is not None else None

    bid = _num(_first(q, "bp", "bid_price", "bidPrice", "bid"))
    ask = _num(_first(q, "ap", "ask_price", "askPrice", "ask"))
    bid_size = _num(_first(q, "bs", "bid_size", "bidSize"))
    ask_size = _num(_first(q, "as", "ask_size", "askSize"))

    last = _num(_first(t, "p", "price", "last"))

    # Volume: prefer daily bar volume when present.
    daily = snapshot.get("dailyBar") or snapshot.get("daily_bar") or snapshot.get("day") or {}
    vol = _num(_first(snapshot, "volume", "v") or _first(daily, "v", "volume"))

    oi = _num(_first(snapshot, "openInterest", "open_interest", "oi"))
    iv = _num(_first(snapshot, "impliedVolatility", "implied_volatility", "iv"))

    delta = _num(_first(greeks, "delta"))
    gamma = _num(_first(greeks, "gamma"))
    theta = _num(_first(greeks, "theta"))
    vega = _num(_first(greeks, "vega"))

    # Some APIs nest greeks/iv under `snapshot.impliedVolatility` etc; keep fallbacks.
    if delta is None:
        delta = _num(_get_nested(snapshot, ("greeks", "delta")))

    return OptionSnapshotView(
        contract_symbol=str(contract_symbol).strip().upper(),
        snapshot_time=snap_ts_s,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        last=last,
        volume=vol,
        open_interest=oi,
        implied_volatility=iv,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
    )


def _liquidity_sort_key(view: OptionSnapshotView) -> tuple:
    """
    Deterministic liquidity key (smaller is better).

    Priority:
    1) tighter spread_pct
    2) deeper min quote size (descending)
    3) larger volume (descending)
    4) larger open interest (descending)
    5) deterministic fallback: contract symbol
    """
    spread_pct = view.spread_pct
    # Treat missing values as worst.
    spread_key = float(spread_pct) if spread_pct is not None else float("inf")

    min_sz = view.min_quote_size
    min_sz_key = -(float(min_sz) if min_sz is not None else 0.0)

    vol = view.volume
    vol_key = -(float(vol) if vol is not None else 0.0)

    oi = view.open_interest
    oi_key = -(float(oi) if oi is not None else 0.0)

    return (spread_key, min_sz_key, vol_key, oi_key, view.contract_symbol)


def _selection_key(
    *,
    contract: OptionContract,
    view: OptionSnapshotView,
    underlying_price: float,
    today_ny: date,
) -> tuple:
    dte = (contract.expiration - today_ny).days
    atm_dist = abs(float(contract.strike) - float(underlying_price))
    return (
        int(dte),  # prefer 0DTE over 1DTE for scalper
        float(atm_dist),
        *_liquidity_sort_key(view),
        float(contract.strike),
        contract.occ_symbol,
    )


def select_spy_scalper_contract(
    *,
    right: OptionRight,
    now_utc: Optional[datetime] = None,
    dte_max: int = 1,
    near_atm_strikes_per_exp: int = 3,
    options_feed: Optional[str] = None,
    stock_feed: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Deterministically select a single SPY option contract (call/put) for scalping.

    Returns a dict with:
    - contract_symbol
    - metadata (expiration, strike, right, dte, underlying_price, quote fields, liquidity diagnostics)
    """
    if right not in ("call", "put"):
        raise ValueError("right must be 'call' or 'put'")
    dte_max = max(0, int(dte_max))
    near_atm_strikes_per_exp = max(1, int(near_atm_strikes_per_exp))

    now = now_utc if now_utc is not None else utc_now()
    today_ny = to_nyse(now).date()
    exp_lte = today_ny + timedelta(days=dte_max)

    env = load_alpaca_env(require_keys=True)
    hdrs = _headers(key_id=env.key_id, secret_key=env.secret_key)

    underlying_price = fetch_underlying_latest_price(
        data_host=env.data_host,
        headers=hdrs,
        symbol="SPY",
        stock_feed=stock_feed,
    )

    raw_contracts = fetch_option_contracts(
        trading_host=env.trading_host,
        headers=hdrs,
        underlying="SPY",
        expiration_gte=today_ny,
        expiration_lte=exp_lte,
    )
    contracts_all = [c for c in (_contract_from_api(x) for x in raw_contracts) if c is not None]

    # Filter to requested right and strict DTE 0..dte_max in NY calendar days.
    contracts = [
        c
        for c in contracts_all
        if c.right == right and 0 <= (c.expiration - today_ny).days <= dte_max
    ]
    if not contracts:
        raise RuntimeError(f"No SPY {right} contracts found for DTE 0..{dte_max} (today_ny={today_ny.isoformat()})")

    # Narrow to a few nearest-ATM strikes per expiration to keep snapshot calls small/deterministic.
    by_exp: Dict[date, List[OptionContract]] = {}
    for c in contracts:
        by_exp.setdefault(c.expiration, []).append(c)

    shortlist: List[OptionContract] = []
    for exp in sorted(by_exp.keys()):
        cs = by_exp[exp]
        cs_sorted = sorted(cs, key=lambda c: (abs(c.strike - underlying_price), c.strike, c.occ_symbol))
        shortlist.extend(cs_sorted[:near_atm_strikes_per_exp])

    shortlist = sorted({c.occ_symbol: c for c in shortlist}.values(), key=lambda c: c.occ_symbol)

    snaps = fetch_option_snapshots(
        data_host=env.data_host,
        headers=hdrs,
        contract_symbols=[c.occ_symbol for c in shortlist],
        options_feed=options_feed,
    )

    candidates: List[tuple[OptionContract, OptionSnapshotView]] = []
    for c in shortlist:
        raw = snaps.get(c.occ_symbol)
        if not isinstance(raw, Mapping):
            continue
        view = _snapshot_view(c.occ_symbol, raw)
        candidates.append((c, view))
    if not candidates:
        raise RuntimeError("No snapshots returned for shortlisted contracts; cannot select deterministically.")

    best_c, best_v = sorted(
        candidates,
        key=lambda cv: _selection_key(contract=cv[0], view=cv[1], underlying_price=underlying_price, today_ny=today_ny),
    )[0]

    dte = (best_c.expiration - today_ny).days
    meta = {
        "underlying_symbol": "SPY",
        "right": best_c.right,
        "expiration": best_c.expiration.isoformat(),
        "strike": float(best_c.strike),
        "dte": int(dte),
        "today_ny": today_ny.isoformat(),
        "asof_utc": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "underlying_price": float(underlying_price),
        "snapshot_time": best_v.snapshot_time,
        "bid": best_v.bid,
        "ask": best_v.ask,
        "bid_size": best_v.bid_size,
        "ask_size": best_v.ask_size,
        "mid": best_v.mid,
        "spread": best_v.spread,
        "spread_pct": best_v.spread_pct,
        "volume": best_v.volume,
        "open_interest": best_v.open_interest,
        "implied_volatility": best_v.implied_volatility,
        "greeks": {"delta": best_v.delta, "gamma": best_v.gamma, "theta": best_v.theta, "vega": best_v.vega},
        "liquidity_rank_key": list(_liquidity_sort_key(best_v)[:-1]),  # omit symbol to keep it compact
    }
    return {"contract_symbol": best_c.occ_symbol, "metadata": meta}


def select_spy_scalper_contracts(
    *,
    now_utc: Optional[datetime] = None,
    dte_max: int = 1,
    near_atm_strikes_per_exp: int = 3,
    options_feed: Optional[str] = None,
    stock_feed: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience: select both a call and a put (each single-leg).
    """
    call = select_spy_scalper_contract(
        right="call",
        now_utc=now_utc,
        dte_max=dte_max,
        near_atm_strikes_per_exp=near_atm_strikes_per_exp,
        options_feed=options_feed,
        stock_feed=stock_feed,
    )
    put = select_spy_scalper_contract(
        right="put",
        now_utc=now_utc,
        dte_max=dte_max,
        near_atm_strikes_per_exp=near_atm_strikes_per_exp,
        options_feed=options_feed,
        stock_feed=stock_feed,
    )
    return {"underlying_symbol": "SPY", "call": call, "put": put}


__all__ = [
    "OptionContract",
    "OptionSnapshotView",
    "fetch_underlying_latest_price",
    "fetch_option_contracts",
    "fetch_option_snapshots",
    "select_spy_scalper_contract",
    "select_spy_scalper_contracts",
]

