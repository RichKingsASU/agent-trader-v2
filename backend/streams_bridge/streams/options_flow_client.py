import asyncio
import logging
import websockets
import json
from datetime import datetime, timezone
from backend.streams_bridge.config import Config
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import map_devconsole_options_flow
from backend.observability.ops_json_logger import OpsLogger

logger = logging.getLogger(__name__)

class OptionsFlowClient:
    def __init__(self, cfg: Config, writer: FirestoreWriter):
        self.cfg = cfg
        self.writer = writer
        self._ops = OpsLogger("stream-bridge")

    async def run_forever(self):
        if not self.cfg.options_flow_url:
            logger.warning("OPTIONS_FLOW_URL not set; options flow client idle.")
            while True:
                await asyncio.sleep(30)
            return

        attempt = 0
        while True:
            try:
                headers = {}
                if self.cfg.options_flow_api_key:
                    headers['Authorization'] = f'Bearer {self.cfg.options_flow_api_key}'

                async with websockets.connect(self.cfg.options_flow_url, extra_headers=headers) as websocket:
                    attempt = 0
                    logger.info("Connected to options flow stream.")
                    try:
                        self._ops.event("connected", stream="options_flow")
                    except Exception:
                        pass
                    while True:
                        message = await websocket.recv()
                        payload = json.loads(message)
                        # Handle both single and array payloads
                        events_payload = payload if isinstance(payload, list) else [payload]
                        events = [map_devconsole_options_flow(ep) for ep in events_payload]
                        await self.writer.insert_options_flow(events)
            except asyncio.CancelledError:
                # Ensure task cancellation triggers a clean process shutdown.
                raise
            except Exception as e:
                logger.exception(f"OptionsFlowClient error: {e}")
                attempt += 1
                sleep_s = 5.0
                try:
                    self._ops.reconnect_attempt(attempt=attempt, sleep_s=sleep_s, stream="options_flow", error=str(e))
                except Exception:
                    pass
                await asyncio.sleep(sleep_s)
