from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence

import requests

from backend.common.env import get_alpaca_api_base_url, get_alpaca_key_id, get_alpaca_secret_key
from backend.marketdata.options.models import OptionContract, parse_option_right


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _headers(*, key_id: Optional[str] = None, secret_key: Optional[str] = None) -> Dict[str, str]:
    key = (key_id or get_alpaca_key_id(required=True) or "").strip()
    secret = (secret_key or get_alpaca_secret_key(required=True) or "").strip()
    if not key or not secret:
        raise RuntimeError("Missing Alpaca API credentials (APCA_API_KEY_ID / APCA_API_SECRET_KEY)")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _request_json(
    url: str,
    *,
    headers: Mapping[str, str],
    params: Optional[Mapping[str, Any]] = None,
    timeout_s: float = 30.0,
) -> Mapping[str, Any]:
    r = requests.get(url, headers=dict(headers), params=dict(params or {}), timeout=timeout_s)
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, Mapping) else {}


def fetch_latest_underlying_price(
    *,
    symbol: str,
    data_host: str = "https://data.alpaca.markets",
    stock_feed: Optional[str] = "iex",
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout_s: float = 30.0,
) -> float:
    """
    Read-only latest underlying price via Alpaca data endpoints.

    Tries latest trade first; falls back to latest quote mid.
    """
    hdrs = _headers(key_id=key_id, secret_key=secret_key)
    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("symbol is required")

    trade_url = f"{data_host.rstrip('/')}/v2/stocks/{sym}/trades/latest"
    trade_params: Dict[str, Any] = {}
    if stock_feed:
        trade_params["feed"] = stock_feed
    try:
        payload = _request_json(trade_url, headers=hdrs, params=trade_params, timeout_s=timeout_s)
        trade = payload.get("trade") if isinstance(payload.get("trade"), Mapping) else {}
        p = _num((trade or {}).get("p") or (trade or {}).get("price"))
        if p is not None and p > 0:
            return p
    except Exception:
        # fall back to quote
        pass

    quote_url = f"{data_host.rstrip('/')}/v2/stocks/{sym}/quotes/latest"
    quote_params: Dict[str, Any] = {}
    if stock_feed:
        quote_params["feed"] = stock_feed
    payload = _request_json(quote_url, headers=hdrs, params=quote_params, timeout_s=timeout_s)
    quote = payload.get("quote") if isinstance(payload.get("quote"), Mapping) else {}
    bid = _num((quote or {}).get("bp") or (quote or {}).get("bid_price") or (quote or {}).get("bidPrice"))
    ask = _num((quote or {}).get("ap") or (quote or {}).get("ask_price") or (quote or {}).get("askPrice"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0

    raise RuntimeError(f"Unable to determine latest price for {sym}")


def fetch_option_contracts(
    *,
    underlying_symbol: str,
    expiration_date_gte: date,
    expiration_date_lte: date,
    trading_host: Optional[str] = None,
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    limit: int = 10000,
    max_pages: int = 25,
    timeout_s: float = 30.0,
) -> List[OptionContract]:
    """
    Read-only option contracts via Alpaca trading endpoint.

    Uses: GET {TRADING}/v2/options/contracts
    """
    hdrs = _headers(key_id=key_id, secret_key=secret_key)
    base = (trading_host or get_alpaca_api_base_url(required=True) or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("Missing Alpaca trading host (APCA_API_BASE_URL)")

    underlying = str(underlying_symbol).strip().upper()
    if not underlying:
        raise ValueError("underlying_symbol is required")

    url = f"{base}/v2/options/contracts"
    page_token: Optional[str] = None
    out: List[OptionContract] = []

    for _ in range(max_pages):
        params: Dict[str, Any] = {
            "underlying_symbols": underlying,
            "expiration_date_gte": expiration_date_gte.isoformat(),
            "expiration_date_lte": expiration_date_lte.isoformat(),
            "limit": int(limit),
        }
        if page_token:
            params["page_token"] = page_token

        payload = _request_json(url, headers=hdrs, params=params, timeout_s=timeout_s)
        raw = payload.get("option_contracts") or payload.get("contracts") or payload.get("results") or []
        if not isinstance(raw, list):
            raw = []

        for c in raw:
            if not isinstance(c, Mapping):
                continue
            sym = str(c.get("symbol") or c.get("option_symbol") or c.get("id") or "").strip().upper()
            exp_s = str(c.get("expiration_date") or c.get("expirationDate") or c.get("expiration") or "").strip()
            strike = _num(c.get("strike_price") or c.get("strike") or c.get("strikePrice"))
            right_raw = c.get("type") or c.get("option_type") or c.get("right")
            if not sym or not exp_s or strike is None or right_raw is None:
                continue
            try:
                exp = date.fromisoformat(exp_s[:10])
                right = parse_option_right(right_raw)
            except Exception:
                continue
            out.append(
                OptionContract(
                    symbol=sym,
                    underlying_symbol=underlying,
                    expiration_date=exp,
                    strike=float(strike),
                    right=right,
                )
            )

        page_token = payload.get("next_page_token") or payload.get("next_page_token".upper())
        if not page_token:
            break

    return out


def fetch_option_snapshots(
    *,
    option_symbols: Sequence[str],
    data_host: str = "https://data.alpaca.markets",
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout_s: float = 30.0,
    chunk_size: int = 200,
) -> Dict[str, Any]:
    """
    Read-only Alpaca option snapshots by OCC/contract symbol.

    Uses: GET {DATA}/v1beta1/options/snapshots?symbols=...
    """
    hdrs = _headers(key_id=key_id, secret_key=secret_key)
    symbols = sorted({str(s).strip().upper() for s in option_symbols if str(s).strip()})
    if not symbols:
        return {}

    url = f"{data_host.rstrip('/')}/v1beta1/options/snapshots"
    out: Dict[str, Any] = {}
    for i in range(0, len(symbols), int(chunk_size)):
        chunk = symbols[i : i + int(chunk_size)]
        payload = _request_json(url, headers=hdrs, params={"symbols": ",".join(chunk)}, timeout_s=timeout_s)
        snaps = payload.get("snapshots")
        if snaps is None:
            snaps = payload
        if isinstance(snaps, Mapping):
            out.update(dict(snaps))
    return out

