"""
Tiny stdlib HTTP server for /ops/status + /metrics.

Used by non-web processes (e.g., strategy engine) that still need endpoints
for scraping and SLO checks.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

from backend.common.ops_metrics import REGISTRY, errors_total


class OpsHttpServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        service_name: str,
        status_fn: Callable[[], dict[str, Any]],
    ) -> None:
        self._host = str(host)
        self._port = int(port)
        self._service_name = str(service_name)
        self._status_fn = status_fn
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        service_name = self._service_name
        status_fn = self._status_fn

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                # Keep default server logs quiet (we prefer structured app logs).
                return

            def _send(self, *, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                try:
                    if self.path in ("/health", "/healthz", "/ops/health"):
                        payload = {"status": "ok", "service": service_name}
                        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                        return self._send(code=200, body=body, content_type="application/json; charset=utf-8")

                    if self.path == "/ops/status":
                        payload = status_fn() or {}
                        # Back-compat: legacy payloads used {"status":"ok","service":...}.
                        # If the shared OpsStatus contract is present, don't inject extra keys.
                        if "service_name" not in payload:
                            payload.setdefault("status", "ok")
                            payload.setdefault("service", service_name)
                        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                        return self._send(code=200, body=body, content_type="application/json; charset=utf-8")

                    if self.path == "/metrics":
                        body = REGISTRY.render_prometheus_text().encode("utf-8")
                        return self._send(
                            code=200,
                            body=body,
                            content_type="text/plain; version=0.0.4; charset=utf-8",
                        )
                    if self.path == "/ops/metrics":
                        body = REGISTRY.render_prometheus_text().encode("utf-8")
                        return self._send(
                            code=200,
                            body=body,
                            content_type="text/plain; version=0.0.4; charset=utf-8",
                        )

                    body = b"not found\n"
                    return self._send(code=404, body=body, content_type="text/plain; charset=utf-8")
                except Exception as e:  # pragma: no cover
                    errors_total.inc(labels={"component": service_name})
                    body = (f"error: {type(e).__name__}: {e}\n").encode("utf-8")
                    return self._send(code=500, body=body, content_type="text/plain; charset=utf-8")

        self._httpd = ThreadingHTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"ops-http-{service_name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        finally:
            self._httpd.server_close()

