import asyncio
import logging
import websockets
import json
from datetime import datetime, timezone
from backend.streams_bridge.config import Config
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import map_devconsole_account_update

logger = logging.getLogger(__name__)

class AccountUpdatesClient:
    def __init__(self, cfg: Config, writer: FirestoreWriter):
        self.cfg = cfg
        self.writer = writer

    async def run_forever(self):
        if not self.cfg.account_updates_url:
            logger.warning("ACCOUNT_UPDATES_URL not set; account updates client idle.")
            while True:
                await asyncio.sleep(30)
            return

        while True:
            try:
                headers = {}
                if self.cfg.account_updates_api_key:
                    headers['Authorization'] = f'Bearer {self.cfg.account_updates_api_key}'

                async with websockets.connect(self.cfg.account_updates_url, extra_headers=headers) as websocket:
                    logger.info("Connected to account updates stream.")
                    while True:
                        message = await websocket.recv()
                        payload = json.loads(message)
                        positions, balances, account_meta = map_devconsole_account_update(payload)
                        await self.writer.write_account_update(
                            account_meta=account_meta,
                            positions=positions,
                            balances=balances,
                        )

            except Exception as e:
                logger.exception(f"AccountUpdatesClient error: {e}")
                await asyncio.sleep(5)
