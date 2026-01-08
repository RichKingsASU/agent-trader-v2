from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class FirecrackerAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirecrackerResponse:
    status: int
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class UnixHTTPClient:
    """
    Minimal HTTP/1.1 client over a Unix domain socket for Firecracker's API.
    """

    def __init__(self, sock_path: str, timeout_s: float = 2.0):
        self.sock_path = sock_path
        self.timeout_s = timeout_s

    def request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> FirecrackerResponse:
        body = b""
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        req_lines = [
            f"{method} {path} HTTP/1.1",
            "Host: localhost",
            "Accept: application/json",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        req = "\r\n".join(req_lines).encode("ascii") + body

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout_s)
        try:
            s.connect(self.sock_path)
            s.sendall(req)
            buf = bytearray()
            recv_iter = 0
            while True:
                recv_iter += 1
                try:
                    chunk = s.recv(65536)
                except Exception:
                    logger.exception("firecracker_api recv_error iteration=%d", recv_iter)
                    raise
                if not chunk:
                    break
                buf.extend(chunk)
            logger.info("firecracker_api recv_loop_iteration=%d", recv_iter)
        finally:
            try:
                s.close()
            except Exception:
                pass

        status, body_bytes = _parse_http_response(bytes(buf))
        return FirecrackerResponse(status=status, body=body_bytes)


def _parse_http_response(raw: bytes) -> Tuple[int, bytes]:
    # Very small parser: split headers/body, parse status line.
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        raise FirecrackerAPIError("invalid HTTP response from firecracker")
    lines = head.split(b"\r\n")
    if not lines:
        raise FirecrackerAPIError("empty HTTP response")
    status_line = lines[0].decode("ascii", errors="replace")
    parts = status_line.split()
    if len(parts) < 2:
        raise FirecrackerAPIError(f"invalid status line: {status_line}")
    try:
        status = int(parts[1])
    except ValueError as e:
        raise FirecrackerAPIError(f"invalid status code: {status_line}") from e
    return status, body

