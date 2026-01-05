import asyncio
import logging
from backend.streams_bridge.config import Config
from backend.streams_bridge.firestore_writer import FirestoreWriter

logger = logging.getLogger(__name__)

class PriceStreamClient:
    def __init__(self, cfg: Config, writer: FirestoreWriter):
        self.cfg = cfg
        self.writer = writer

    async def run_forever(self):
        while True:
            try:
                # TODO: Wire this to the actual Developer Console WebSocket/API endpoint.
                logger.info("stream_bridge: price stream client placeholder")
                await asyncio.sleep(10)
            except Exception as e:
                logger.exception(f"PriceStreamClient error: {e}")
                await asyncio.sleep(5)
