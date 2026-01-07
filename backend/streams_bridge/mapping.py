import json
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from backend.time.providers import normalize_alpaca_timestamp

def map_devconsole_news(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps a raw Developer Console news payload to the normalized news_events schema.
    TODO: Adjust field names based on actual Developer Console news payload structure (e.g., Benzinga).
    """
    event_ts_str = payload.get("timestamp") or payload.get("published_at")
    event_ts = normalize_alpaca_timestamp(event_ts_str) if event_ts_str else datetime.now(timezone.utc)

    return {
        "event_ts": event_ts,
        "source": payload.get("source", "dev_console_news"),
        "symbol": payload.get("symbol") or payload.get("symbols", [None])[0],
        "headline": payload.get("headline") or payload.get("title", "No Headline"),
        "body": payload.get("body") or payload.get("summary"),
        "url": payload.get("url"),
        "category": payload.get("category"),
        "sentiment": payload.get("sentiment"),
        "importance": payload.get("importance"),
        "raw": json.dumps(payload),
    }

def map_devconsole_options_flow(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps a raw Developer Console options flow payload to the normalized options_flow schema.
    TODO: Adjust field names based on actual Developer Console options flow payload structure (e.g., OPRA/Polygon).
    """
    event_ts_str = payload.get("timestamp")
    event_ts = normalize_alpaca_timestamp(event_ts_str) if event_ts_str else datetime.now(timezone.utc)

    expiration_date_str = payload.get("expiration_date")
    expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d').date() if expiration_date_str else None

    return {
        "event_ts": event_ts,
        "symbol": payload.get("underlying_symbol"),
        "option_symbol": payload.get("option_contract_symbol"),
        "side": payload.get("side", "unknown"),
        "size": payload.get("size", 0),
        "notional": payload.get("notional"),
        "strike": payload.get("strike_price"),
        "expiration": expiration_date,
        "option_type": payload.get("option_type"),
        "trade_price": payload.get("trade_price"),
        "bid": payload.get("bid_price"),
        "ask": payload.get("ask_price"),
        "venue": payload.get("exchange"),
        "source": payload.get("source", "dev_console_options"),
        "raw": json.dumps(payload),
    }

def map_devconsole_account_update(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Maps a raw Developer Console account update payload to normalized positions, balances, and account meta.
    TODO: Adjust field names based on actual Developer Console account update payload structure (e.g., TD Ameritrade).
    """
    positions_data = []
    balances_data = []
    account_meta = {"broker": payload.get("broker", "td_ameritrade"), "external_account_id": payload.get("account_id")}
    updated_at_str = payload.get("timestamp")
    updated_at = normalize_alpaca_timestamp(updated_at_str) if updated_at_str else datetime.now(timezone.utc)

    # Example mapping for positions
    for p_raw in payload.get("positions", []):
        positions_data.append({
            "symbol": p_raw.get("instrument_id") or p_raw.get("symbol"),
            "qty": p_raw.get("quantity", 0),
            "avg_price": p_raw.get("average_cost"),
            "market_value": p_raw.get("market_value"),
            "updated_at": updated_at,
            "raw": json.dumps(p_raw),
        })

    # Example mapping for balances
    b_raw = payload.get("balances", {})
    balances_data.append({
        "cash": b_raw.get("cash_balance"),
        "buying_power": b_raw.get("buying_power"),
        "maintenance_margin": b_raw.get("maintenance_margin"),
        "equity": b_raw.get("total_equity"),
        "updated_at": updated_at,
        "raw": json.dumps(b_raw),
    })

    return positions_data, balances_data, account_meta