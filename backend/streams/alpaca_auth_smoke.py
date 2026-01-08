"""
Deterministic Alpaca authentication smoke tests.

Goals:
- REST auth smoke test: GET /v2/account (no side effects).
- WebSocket auth smoke test: connect + auth only (no subscriptions).
- Fast failure on auth errors (401/403).
- Lightweight defaults suitable for CI/VM (short timeouts, minimal retries).

This module is intentionally dependency-light and does not log secrets.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import requests
import websockets

from backend.streams.alpaca_env import AlpacaEnv, load_alpaca_env


class AlpacaAuthSmokeError(RuntimeError):
    """Raised when an Alpaca auth smoke check fails."""


@dataclass(frozen=True, slots=True)
class AlpacaAuthSmokeResult:
    rest_ok: bool
    ws_ok: bool
    trading_host: str
    ws_url: str


def _headers(env: AlpacaEnv) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": env.key_id,
        "APCA-API-SECRET-KEY": env.secret_key,
    }


def _is_auth_status(status_code: int | None) -> bool:
    return status_code in (401, 403)


def _default_data_ws_url(*, feed: str) -> str:
    """
    Alpaca stock market data stream (v2).

    Docs typically use:
    - wss://stream.data.alpaca.markets/v2/iex
    - wss://stream.data.alpaca.markets/v2/sip
    """
    feed_norm = (feed or "iex").strip().lower()
    return f"wss://stream.data.alpaca.markets/v2/{feed_norm}"


def alpaca_rest_account_smoke_test(*, env: AlpacaEnv | None = None, timeout_s: float = 5.0) -> dict[str, Any]:
    """
    REST auth smoke test: calls /v2/account and returns parsed JSON.

    - **No side effects**
    - **Fails fast** on auth errors (401/403)
    """
    env = env or load_alpaca_env(require_keys=True)
    url = f"{env.trading_base_v2}/account"

    # Minimal retry for transient network flakiness (not for auth errors).
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers=_headers(env), timeout=timeout_s)
            if _is_auth_status(r.status_code):
                raise AlpacaAuthSmokeError(
                    f"ALPACA REST auth failed (status={r.status_code}) for GET {url}."
                )
            r.raise_for_status()
            return r.json()
        except AlpacaAuthSmokeError:
            raise
        except Exception as e:
            last_err = e
            # One fast retry for non-auth failures.
            if attempt == 1:
                continue
            status = getattr(getattr(e, "response", None), "status_code", None)
            if _is_auth_status(status):
                raise AlpacaAuthSmokeError(
                    f"ALPACA REST auth failed (status={status}) for GET {url}."
                ) from e
            raise AlpacaAuthSmokeError(f"ALPACA REST smoke test failed for GET {url}: {type(e).__name__}: {e}") from e

    # Defensive (loop always returns/raises).
    raise AlpacaAuthSmokeError(f"ALPACA REST smoke test failed for GET {url}: {last_err}")


def _extract_ws_event_objects(msg: Any) -> list[dict[str, Any]]:
    if isinstance(msg, list):
        return [m for m in msg if isinstance(m, dict)]
    if isinstance(msg, dict):
        return [msg]
    return []


def _ws_is_authenticated(events: list[dict[str, Any]]) -> bool:
    # Common Alpaca v2 stream format: {"T":"success","msg":"authenticated"}
    for e in events:
        t = (e.get("T") or e.get("type") or "").lower()
        msg = (e.get("msg") or e.get("message") or "").lower()
        if t == "success" and "authenticated" in msg:
            return True
    return False


def _ws_auth_error(events: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    # Common error format: {"T":"error","code":401,"msg":"auth failed"}
    for e in events:
        t = (e.get("T") or e.get("type") or "").lower()
        if t == "error":
            code = e.get("code")
            try:
                code_int = int(code) if code is not None else None
            except Exception:
                code_int = None
            msg = e.get("msg") or e.get("message")
            return code_int, str(msg) if msg is not None else None
    return None, None


async def alpaca_ws_auth_smoke_test(
    *,
    env: AlpacaEnv | None = None,
    feed: str = "iex",
    timeout_s: float = 5.0,
    ws_url: str | None = None,
) -> None:
    """
    WebSocket auth smoke test: connect + auth only (no subscriptions).
    """
    env = env or load_alpaca_env(require_keys=True)

    ws_url = (
        (ws_url or "").strip()
        or os.getenv("ALPACA_DATA_STREAM_WS_URL", "").strip()
        or _default_data_ws_url(feed=feed)
    )

    auth_payload = {"action": "auth", "key": env.key_id, "secret": env.secret_key}

    try:
        async with websockets.connect(
            ws_url,
            open_timeout=timeout_s,
            close_timeout=min(2.0, timeout_s),
            ping_interval=None,  # keep it simple; auth handshake only
        ) as ws:
            await ws.send(json.dumps(auth_payload, separators=(",", ":")))
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)

            try:
                parsed = json.loads(raw)
            except Exception as e:
                raise AlpacaAuthSmokeError(
                    f"ALPACA WS smoke test failed: non-JSON auth response from {ws_url}: {raw!r}"
                ) from e

            events = _extract_ws_event_objects(parsed)
            if _ws_is_authenticated(events):
                return

            code, msg = _ws_auth_error(events)
            if _is_auth_status(code):
                raise AlpacaAuthSmokeError(
                    f"ALPACA WS auth failed (code={code}) for {ws_url}: {msg or 'authentication failed'}"
                )

            raise AlpacaAuthSmokeError(
                f"ALPACA WS smoke test failed for {ws_url}: unexpected auth response: {parsed!r}"
            )
    except AlpacaAuthSmokeError:
        raise
    except Exception as e:
        raise AlpacaAuthSmokeError(f"ALPACA WS smoke test failed for {ws_url}: {type(e).__name__}: {e}") from e


async def run_alpaca_auth_smoke_tests_async(
    *,
    feed: str = "iex",
    timeout_s: float = 5.0,
    skip_if_missing_creds: bool = False,
) -> AlpacaAuthSmokeResult:
    """
    Runs both REST + WS auth smoke tests (intended for startup gating).
    """
    try:
        env = load_alpaca_env(require_keys=not skip_if_missing_creds)
    except Exception as e:
        if skip_if_missing_creds:
            raise AlpacaAuthSmokeError(
                "ALPACA auth smoke tests skipped/blocked: missing Alpaca credentials."
            ) from e
        raise

    if not env.key_id or not env.secret_key:
        if skip_if_missing_creds:
            raise AlpacaAuthSmokeError("ALPACA auth smoke tests skipped: missing Alpaca credentials.")
        raise AlpacaAuthSmokeError("ALPACA auth smoke tests require credentials but none were provided.")

    acct = alpaca_rest_account_smoke_test(env=env, timeout_s=timeout_s)
    # Safe-to-log fields only.
    acct_id = acct.get("id")
    acct_status = acct.get("status")

    ws_url = os.getenv("ALPACA_DATA_STREAM_WS_URL", "").strip() or _default_data_ws_url(feed=feed)
    await alpaca_ws_auth_smoke_test(env=env, feed=feed, timeout_s=timeout_s, ws_url=ws_url)

    # Emit concise success messages (no secrets).
    try:
        from backend.common.ops_log import log_json as _log_json  # noqa: WPS433

        _log_json(
            intent_type="alpaca_auth_smoke",
            severity="INFO",
            status="pass",
            rest_ok=True,
            ws_ok=True,
            trading_host=env.trading_host,
            account_id=acct_id,
            account_status=acct_status,
            ws_url=ws_url,
        )
    except Exception:
        pass

    return AlpacaAuthSmokeResult(
        rest_ok=True,
        ws_ok=True,
        trading_host=env.trading_host,
        ws_url=ws_url,
    )


def run_alpaca_auth_smoke_tests(
    *,
    feed: str = "iex",
    timeout_s: float = 5.0,
    skip_if_missing_creds: bool = False,
) -> AlpacaAuthSmokeResult:
    """
    Synchronous wrapper for environments without an event loop.
    """
    return asyncio.run(
        run_alpaca_auth_smoke_tests_async(
            feed=feed,
            timeout_s=timeout_s,
            skip_if_missing_creds=skip_if_missing_creds,
        )
    )

