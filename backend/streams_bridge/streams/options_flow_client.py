import asyncio
import logging
import websockets
import json
from datetime import datetime, timezone
from backend.streams_bridge.config import Config
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import map_devconsole_options_flow
from backend.observability.ops_json_logger import OpsLogger
from backend.common.logging import log_event
from backend.common.ops_metrics import messages_received_total, messages_published_total, reconnect_attempts_total

logger = logging.getLogger(__name__)

class OptionsFlowClient:
    def __init__(self, cfg: Config, writer: FirestoreWriter):
        self.cfg = cfg
        self.writer = writer
        self._ops = OpsLogger("stream-bridge")
        self._recv_total = 0
        self._pub_total = 0
        self._reconnect_total = 0
        self._last_stats_log_m = 0.0
        self._recv_since_log = 0
        self._pub_since_log = 0

    def _maybe_log_stats(self) -> None:
        # Log aggregated counts periodically (avoid per-message log spam).
        now_m = asyncio.get_running_loop().time()
        if self._last_stats_log_m and (now_m - self._last_stats_log_m) < 30.0:
            return
        self._last_stats_log_m = now_m
        try:
            log_event(
                logger,
                "stream_stats",
                severity="INFO",
                component="stream-bridge",
                stream="options_flow",
                received_total=int(self._recv_total),
                published_total=int(self._pub_total),
                reconnect_attempts_total=int(self._reconnect_total),
                received_since_last=int(self._recv_since_log),
                published_since_last=int(self._pub_since_log),
            )
        except Exception:
            logger.exception("stream_bridge.options_flow.log_stats_failed")
            pass
        self._recv_since_log = 0
        self._pub_since_log = 0

    async def run_forever(self):
        if not self.cfg.options_flow_url:
            logger.warning("OPTIONS_FLOW_URL not set; options flow client idle.")
            idle_iter = 0
            while True:
                idle_iter += 1
                logger.info("options_flow idle_loop_iteration=%d", idle_iter)
                await asyncio.sleep(30)
            return

        attempt = 0
        loop_iter = 0
        while True:
            loop_iter += 1
            logger.info("options_flow connect_loop_iteration=%d", loop_iter)
            try:
                headers = {}
                if self.cfg.options_flow_api_key:
                    headers['Authorization'] = f'Bearer {self.cfg.options_flow_api_key}'

                try:
                    log_event(
                        logger,
                        "ws_connect_attempt",
                        severity="INFO",
                        component="stream-bridge",
                        stream="options_flow",
                        attempt=int(attempt + 1),
                        auth_present=bool(self.cfg.options_flow_api_key),
                        url_configured=True,
                    )
                except Exception:
                    logger.exception("stream_bridge.options_flow.ws_connect_attempt_log_failed")
                    pass

                async with websockets.connect(self.cfg.options_flow_url, extra_headers=headers) as websocket:
                    attempt = 0
                    recv_iter = 0
                    try:
                        log_event(
                            logger,
                            "ws_connected",
                            severity="INFO",
                            component="stream-bridge",
                            stream="options_flow",
                        )
                    except Exception:
                        logger.exception("stream_bridge.options_flow.ws_connected_log_failed")
                        pass
                    try:
                        self._ops.event("connected", stream="options_flow")
                    except Exception:
                        logger.exception("stream_bridge.options_flow.ops_connected_event_failed")
                        pass
                    while True:
                        message = await websocket.recv()
                        recv_iter += 1
                        if recv_iter % 100 == 0:
                            logger.info("options_flow recv_loop_iteration=%d", recv_iter)
                        self._recv_total += 1
                        self._recv_since_log += 1
                        try:
                            messages_received_total.inc(1.0, labels={"component": "stream-bridge", "stream": "options_flow"})
                        except Exception:
                            logger.exception("stream_bridge.options_flow.metrics_messages_received_inc_failed")
                            pass
                        payload = json.loads(message)
                        # Handle both single and array payloads
                        events_payload = payload if isinstance(payload, list) else [payload]
                        events = [map_devconsole_options_flow(ep) for ep in events_payload]
                        await self.writer.insert_options_flow(events)
                        published_n = int(len(events))
                        self._pub_total += published_n
                        self._pub_since_log += published_n
                        try:
                            messages_published_total.inc(
                                float(published_n),
                                labels={"component": "stream-bridge", "stream": "options_flow"},
                            )
                        except Exception:
                            logger.exception("stream_bridge.options_flow.metrics_messages_published_inc_failed")
                            pass
                        self._maybe_log_stats()
            except Exception as e:
                try:
                    log_event(
                        logger,
                        "ws_disconnected",
                        severity="WARNING",
                        component="stream-bridge",
                        stream="options_flow",
                        error=f"{type(e).__name__}: {e}",
                    )
                except Exception:
                    logger.exception("stream_bridge.options_flow.ws_disconnected_log_failed")
                    pass
                logger.exception(f"OptionsFlowClient error: {e}")
                attempt += 1
                self._reconnect_total += 1
                try:
                    reconnect_attempts_total.inc(1.0, labels={"component": "stream-bridge", "stream": "options_flow"})
                except Exception:
                    logger.exception("stream_bridge.options_flow.metrics_reconnect_attempt_inc_failed")
                    pass
                sleep_s = 5.0
                try:
                    self._ops.reconnect_attempt(attempt=attempt, sleep_s=sleep_s, stream="options_flow", error=str(e))
                except Exception:
                    logger.exception("stream_bridge.options_flow.ops_reconnect_attempt_log_failed")
                    pass
                await asyncio.sleep(sleep_s)
