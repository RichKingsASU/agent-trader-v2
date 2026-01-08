import asyncio
import logging
import websockets
import json
from datetime import datetime, timezone
from backend.streams_bridge.config import Config
from backend.streams_bridge.firestore_writer import FirestoreWriter
from backend.streams_bridge.mapping import map_devconsole_news
from backend.common.logging import log_event
from backend.common.ops_metrics import messages_received_total, messages_published_total, reconnect_attempts_total

logger = logging.getLogger(__name__)

class NewsStreamClient:
    def __init__(self, cfg: Config, writer: FirestoreWriter):
        self.cfg = cfg
        self.writer = writer
        self._recv_total = 0
        self._pub_total = 0
        self._reconnect_total = 0
        self._last_stats_log_m = 0.0
        self._recv_since_log = 0
        self._pub_since_log = 0

    def _maybe_log_stats(self) -> None:
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
                stream="news",
                received_total=int(self._recv_total),
                published_total=int(self._pub_total),
                reconnect_attempts_total=int(self._reconnect_total),
                received_since_last=int(self._recv_since_log),
                published_since_last=int(self._pub_since_log),
            )
        except Exception:
            pass
        self._recv_since_log = 0
        self._pub_since_log = 0

    async def run_forever(self):
        if not self.cfg.news_stream_url:
            logger.warning("NEWS_STREAM_URL not set; news stream client idle.")
            while True:
                await asyncio.sleep(30)
            return

        attempt = 0
        while True:
            try:
                headers = {}
                if self.cfg.news_stream_api_key:
                    headers['Authorization'] = f'Bearer {self.cfg.news_stream_api_key}'

                try:
                    log_event(
                        logger,
                        "ws_connect_attempt",
                        severity="INFO",
                        component="stream-bridge",
                        stream="news",
                        attempt=int(attempt + 1),
                        auth_present=bool(self.cfg.news_stream_api_key),
                        url_configured=True,
                    )
                except Exception:
                    pass

                async with websockets.connect(self.cfg.news_stream_url, extra_headers=headers) as websocket:
                    attempt = 0
                    try:
                        log_event(
                            logger,
                            "ws_connected",
                            severity="INFO",
                            component="stream-bridge",
                            stream="news",
                        )
                    except Exception:
                        pass
                    while True:
                        message = await websocket.recv()
                        self._recv_total += 1
                        self._recv_since_log += 1
                        try:
                            messages_received_total.inc(1.0, labels={"component": "stream-bridge", "stream": "news"})
                        except Exception:
                            pass
                        payload = json.loads(message)
                        event = map_devconsole_news(payload)
                        await self.writer.insert_news_events([event])
                        self._pub_total += 1
                        self._pub_since_log += 1
                        try:
                            messages_published_total.inc(1.0, labels={"component": "stream-bridge", "stream": "news"})
                        except Exception:
                            pass
                        self._maybe_log_stats()
            except Exception as e:
                try:
                    log_event(
                        logger,
                        "ws_disconnected",
                        severity="WARNING",
                        component="stream-bridge",
                        stream="news",
                        error=f"{type(e).__name__}: {e}",
                    )
                except Exception:
                    pass
                logger.exception(f"NewsStreamClient error: {e}")
                attempt += 1
                self._reconnect_total += 1
                try:
                    reconnect_attempts_total.inc(1.0, labels={"component": "stream-bridge", "stream": "news"})
                except Exception:
                    pass
                await asyncio.sleep(5)
