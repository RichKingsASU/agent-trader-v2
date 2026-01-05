import asyncpg
from typing import List, TypedDict
from dataclasses import dataclass
from datetime import datetime

from .config import config

@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

@dataclass
class FlowEvent:
    ts: datetime
    total_value: float

@dataclass
class Position:
    symbol: str
    qty: float

async def get_db_connection():
    return await asyncpg.connect(config.DATABASE_URL, statement_cache_size=0)

async def fetch_recent_bars(symbol: str, lookback_minutes: int) -> List[Bar]:
    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT ts, open, high, low, close, volume
            FROM public.market_data_1m
            WHERE symbol = $1 AND ts >= NOW() - ($2 * INTERVAL '1 minute')
            ORDER BY ts DESC
            """,
            symbol,
            lookback_minutes
        )
        return [Bar(**row) for row in rows]
    finally:
        await conn.close()

async def fetch_recent_options_flow(symbol: str, lookback_minutes: int) -> List[FlowEvent]:
    conn = await get_db_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT event_ts as ts, notional as total_value
            FROM public.options_flow
            WHERE symbol = $1 AND event_ts >= NOW() - ($2 * INTERVAL '1 minute')
            ORDER BY event_ts DESC
            """,
            symbol,
            lookback_minutes
        )
        # Filter out rows where total_value is None
        return [FlowEvent(**row) for row in rows if row['total_value'] is not None]
    finally:
        await conn.close()

async def fetch_positions() -> List[Position]:
    conn = await get_db_connection()
    try:
        rows = await conn.fetch("SELECT symbol, qty FROM public.broker_positions")
        return [Position(**row) for row in rows]
    finally:
        await conn.close()