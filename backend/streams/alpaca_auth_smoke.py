from __future__ import annotations

import json
import os
from typing import Any

import requests

from backend.streams.alpaca_env import AlpacaEnv, load_alpaca_env


def _truthy(v: str | None) -> bool:
    return bool(str(v or "").strip().lower() in {"1", "true", "t", "yes", "y", "on"})


def run_smoke_tests() -> bool:
    # Opt-in only (avoids accidental network calls in default unit-test runs).
    return _truthy(os.getenv("RUN_ALPACA_AUTH_SMOKE_TESTS"))


def alpaca_rest_account_smoke_test(*, env: AlpacaEnv, timeout_s: float = 5.0) -> dict[str, Any]:
    """
    REST auth-only smoke test (no side effects).
    """
    url = f"{env.trading_host}/v2/account"
    r = requests.get(
        url,
        headers={"APCA-API-KEY-ID": env.key_id, "APCA-API-SECRET-KEY": env.secret_key},
        timeout=max(0.1, float(timeout_s)),
    )
    r.raise_for_status()
    out = r.json() or {}
    return out if isinstance(out, dict) else {"payload": out}


async def alpaca_ws_auth_smoke_test(*, feed: str, timeout_s: float = 5.0) -> None:
    """
    WebSocket auth-only smoke test (no subscriptions; no side effects).
    """
    import asyncio

    import websockets

    env = load_alpaca_env(require_keys=True)
    ws_url = (os.getenv("ALPACA_DATA_STREAM_WS_URL") or "").strip() or f"wss://stream.data.alpaca.markets/v2/{str(feed).strip().lower() or 'iex'}"

    async def _run() -> None:
        async with websockets.connect(ws_url, open_timeout=max(0.1, float(timeout_s))) as ws:
            auth = {"action": "auth", "key": env.key_id, "secret": env.secret_key}
            await ws.send(json.dumps(auth, separators=(",", ":"), ensure_ascii=False))
            # Best-effort: read one server response frame and exit.
            try:
                await asyncio.wait_for(ws.recv(), timeout=max(0.1, float(timeout_s)))
            except Exception:
                return

    await _run()
