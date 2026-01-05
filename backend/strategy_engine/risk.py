import asyncpg
import json
from datetime import date, datetime
from uuid import UUID, uuid4

from .config import config

async def get_db_connection():
    return await asyncpg.connect(config.DATABASE_URL, statement_cache_size=0)

async def get_or_create_strategy_definition(name: str) -> UUID:
    conn = await get_db_connection()
    try:
        strategy_id = await conn.fetchval("SELECT id FROM public.strategy_definitions WHERE name = $1", name)
        if not strategy_id:
            strategy_id = await conn.fetchval(
                "INSERT INTO public.strategy_definitions (name) VALUES ($1) RETURNING id", name
            )
        return strategy_id
    finally:
        await conn.close()

async def get_or_create_today_state(strategy_id: UUID, trading_date: date) -> asyncpg.Record:
    conn = await get_db_connection()
    try:
        state = await conn.fetchrow(
            "SELECT * FROM public.strategy_state WHERE strategy_id = $1 AND trading_date = $2",
            strategy_id,
            trading_date,
        )
        if not state:
            state = await conn.fetchrow(
                """
                INSERT INTO public.strategy_state (strategy_id, trading_date)
                VALUES ($1, $2)
                RETURNING *
                """,
                strategy_id,
                trading_date,
            )
        return state
    finally:
        await conn.close()

async def load_limits(strategy_id: UUID) -> asyncpg.Record:
    conn = await get_db_connection()
    try:
        return await conn.fetchrow("SELECT * FROM public.strategy_limits WHERE strategy_id = $1", strategy_id)
    finally:
        await conn.close()

async def can_place_trade(strategy_id: UUID, trading_date: date, proposed_notional: float) -> bool:
    state = await get_or_create_today_state(strategy_id, trading_date)
    limits = await load_limits(strategy_id)

    if not limits:
        return True # No limits set, so allow trade

    if state['trades_placed'] >= limits.get('max_daily_trades', float('inf')):
        return False
    if state['notional_traded'] + proposed_notional > limits.get('max_notional_per_day', float('inf')):
        return False

    return True

async def record_trade(strategy_id: UUID, trading_date: date, notional: float):
    conn = await get_db_connection()
    try:
        await conn.execute(
            """
            UPDATE public.strategy_state
            SET trades_placed = trades_placed + 1,
                notional_traded = notional_traded + $1,
                last_trade_at = NOW()
            WHERE strategy_id = $2 AND trading_date = $3
            """,
            notional,
            strategy_id,
            trading_date,
        )
    finally:
        await conn.close()

import json

async def log_decision(
    strategy_id: UUID,
    symbol: str,
    decision: str,
    reason: str,
    signal_payload: dict,
    did_trade: bool,
    paper_trade_id: UUID = None,
):
    conn = await get_db_connection()
    try:
        await conn.execute(
            """
            INSERT INTO public.strategy_logs (strategy_id, symbol, decision, reason, signal_payload, did_trade, paper_trade_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            strategy_id,
            symbol,
            decision,
            reason,
            json.dumps(signal_payload),
            did_trade,
            paper_trade_id,
        )
    finally:
        await conn.close()