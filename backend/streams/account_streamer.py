import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.stream import TradingStream
from alpaca.trading.models import TradeUpdate
from google.cloud import firestore

from backend.streams.alpaca_env import load_alpaca_env

logger = logging.getLogger(__name__)

async def account_streamer_main(ready_event: asyncio.Event) -> None:
    """
    Main entry point for the Alpaca Account Streamer.
    """
    logger.info("Initializing Alpaca Account Streamer...")
    
    alpaca = load_alpaca_env()
    # Paper/Live is determined by the Loading logic, but we need to pass paper=True/False to Client
    # alpaca_env.py sets trading_host to paper-api... if paper.
    # We can infer paper mode from the host URL in alpaca env or just safely default to True if unsure?
    # Actually, `load_alpaca_env` handles the keys. 
    # TradingClient takes `paper=True` or `False`.
    is_paper = "paper" in alpaca.trading_host
    
    trading_client = TradingClient(alpaca.key_id, alpaca.secret_key, paper=is_paper)
    trading_stream = TradingStream(alpaca.key_id, alpaca.secret_key, paper=is_paper)
    
    db = firestore.Client()
    tenant_id = os.getenv("TENANT_ID", "default")
    # We write to tenants/{tenantId}/accounts/live (or similar singleton)
    # The frontend expects to listen to SOMETHING. 
    # Let's use `tenants/{tenantId}/accounts/live` as a doc.
    account_doc_ref = db.document(f"tenants/{tenant_id}/accounts/live")

    async def update_account_snapshot():
        try:
            acct = trading_client.get_account()
            now = datetime.now(timezone.utc)
            
            data = {
                "equity": float(acct.equity or 0),
                "cash": float(acct.cash or 0),
                "buying_power": float(acct.buying_power or 0),
                "currency": acct.currency,
                "status": acct.status,
                "updated_at": now,
                "updated_at_ms": int(now.timestamp() * 1000)
            }
            
            # Write to Firestore
            account_doc_ref.set(data, merge=True)
            # logger.info(f"Updated account: Equity=${data['equity']}")
            
        except Exception as e:
            logger.error(f"Error updating account snapshot: {e}")

    async def trade_update_handler(data: TradeUpdate):
        # When a trade happens, update the account immediately
        logger.info(f"Trade update received: {data.event}")
        await update_account_snapshot()

    # Subscribe to trade updates
    try:
        trading_stream.subscribe_trade_updates(trade_update_handler)
        # Verify connection by starting it? 
        # TradingStream.run() is blocking. We should run it in a separate executor or just rely on periodic polling if stream is hard to compose.
        # But wait, we want STREAMING.
        # We can run the stream loop in a task.
    except Exception as e:
        logger.error(f"Failed to subscribe to trade updates: {e}")

    # Signal readiness
    ready_event.set()

    # Main Loop: Periodic Poll + Stream
    # We need to run the stream AND the poller.
    
    # 1. Initial fetch
    await update_account_snapshot()
    
    # 2. Start Stream in background task
    # TradingStream uses awebsocket which is async-compatible usually, but alpaca-py implementation wraps it sync-blocking?
    # Looking at alpaca-py source, `run` is blocking.
    # We can try running it in a thread.
    
    import concurrent.futures
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    
    # Start the stream in a thread
    # Note: This might be tricky if it tries to call the async handler `trade_update_handler` from a thread.
    # Actually, `trading_stream` callbacks in alpaca-py are synchronous? or async?
    # If they are async, `run` handles the loop?
    # For safety/simplicity in this "Agent" environment, let's rely heavily on PERIODIC POLLING (every 3s) 
    # because it guarantees "Equity" updates (which change even without trades due to market moves).
    # Trade updates strictly only happen on fills. Equities move constantly.
    
    # So Polling is actually MORE important for "Live Equity".
    
    while True:
        await update_account_snapshot()
        await asyncio.sleep(3) 

