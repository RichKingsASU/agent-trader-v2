#!/usr/bin/env python3
import os
import json
from datetime import datetime

import psycopg


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL env var is not set")
    return url


def build_raw_order(logical_order: dict) -> dict:
    """
    Build the broker-facing payload (raw_order).
    For now it's just a mirror of the logical order + metadata.
    """
    return {
        "instrument_type": logical_order["instrument_type"],
        "symbol": logical_order["symbol"],
        "side": logical_order["side"],
        "order_type": logical_order["order_type"],
        "time_in_force": logical_order.get("time_in_force", "day"),
        "notional": logical_order["notional"],
        "quantity": logical_order.get("quantity"),
        "strategy_id": logical_order["strategy_id"],
        "broker_account_id": logical_order["broker_account_id"],
        "user_id": logical_order["user_id"],
    }


def insert_paper_order(logical_order: dict) -> dict:
    """
    Convert logical_order into a row in public.paper_orders
    and return a summary of the inserted row.
    """
    db_url = get_db_url()
    raw_order = build_raw_order(logical_order)

    sql = """
    insert into public.paper_orders (
      user_id,
      broker_account_id,
      strategy_id,
      symbol,
      instrument_type,
      side,
      order_type,
      time_in_force,
      notional,
      quantity,
      risk_allowed,
      risk_scope,
      risk_reason,
      raw_order,
      status
    )
    values (
      %(user_id)s,
      %(broker_account_id)s,
      %(strategy_id)s,
      %(symbol)s,
      %(instrument_type)s,
      %(side)s,
      %(order_type)s,
      %(time_in_force)s,
      %(notional)s,
      %(quantity)s,
      %(risk_allowed)s,
      %(risk_scope)s,
      %(risk_reason)s,
      %(raw_order)s,
      'simulated'
    )
    returning id, symbol, notional, status, created_at;
    """

    params = {
        "user_id": logical_order["user_id"],
        "broker_account_id": logical_order["broker_account_id"],
        "strategy_id": logical_order["strategy_id"],
        "symbol": logical_order["symbol"],
        "instrument_type": logical_order["instrument_type"],
        "side": logical_order["side"],
        "order_type": logical_order["order_type"],
        "time_in_force": logical_order.get("time_in_force", "day"),
        "notional": logical_order["notional"],
        "quantity": logical_order.get("quantity"),
        "risk_allowed": logical_order.get("risk_allowed", True),
        "risk_scope": logical_order.get("risk_scope"),
        "risk_reason": logical_order.get("risk_reason"),
        "raw_order": json.dumps(raw_order),
    }

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

    return {
        "id": str(row[0]),
        "symbol": row[1],
        "notional": float(row[2]),
        "status": row[3],
        "created_at": (
            row[4].isoformat() if isinstance(row[4], datetime) else str(row[4])
        ),
    }


def main():
    # Example logical order using YOUR real IDs
    logical_order = {
        "user_id": "2385984e-0ae9-47f1-a82e-3c17e0dad510",
        "broker_account_id": "25904484-f163-4a56-b606-35405123fc22",
        "strategy_id": "37a7bcbe-9cb0-463c-9e37-6e4bd6b97765",
        "symbol": "SPY",
        "instrument_type": "stock",   # or "option" later
        "side": "buy",
        "order_type": "market",
        "time_in_force": "day",
        "notional": 2000.00,
        "quantity": None,
        "risk_allowed": True,
        "risk_scope": "strategy",
        "risk_reason": None,
    }

    inserted = insert_paper_order(logical_order)

    # Plain-language echo for the user
    print(
        f"Inserted paper order {inserted['id']} -> "
        f"{inserted['symbol']} notional ${inserted['notional']:.2f}, "
        f"status={inserted['status']}, created_at={inserted['created_at']}"
    )


if __name__ == "__main__":
    main()
