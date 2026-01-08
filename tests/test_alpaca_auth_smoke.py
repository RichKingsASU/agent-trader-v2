import asyncio
import os

import pytest

from backend.streams.alpaca_auth_smoke import alpaca_rest_account_smoke_test, alpaca_ws_auth_smoke_test
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.ops_log import log_json


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _should_run() -> bool:
    # Opt-in to avoid accidental network calls in default unit-test runs.
    return _truthy(os.getenv("RUN_ALPACA_AUTH_SMOKE_TESTS"))


def _have_creds() -> bool:
    env = load_alpaca_env(require_keys=False)
    return bool(env.key_id and env.secret_key)


def test_alpaca_rest_auth_smoke_v2_account() -> None:
    """
    REST smoke test:
    - Calls /v2/account
    - Fails fast on auth errors
    - No side effects
    """
    if not _should_run():
        pytest.skip("Set RUN_ALPACA_AUTH_SMOKE_TESTS=1 to enable Alpaca auth smoke tests.")
    if not _have_creds():
        pytest.skip("Missing Alpaca credentials (ALPACA_API_KEY/ALPACA_SECRET_KEY).")

    env = load_alpaca_env(require_keys=True)
    acct = alpaca_rest_account_smoke_test(env=env, timeout_s=float(os.getenv("ALPACA_AUTH_SMOKE_TIMEOUT_S", "5")))

    # Keep asserts deterministic and safe (no secrets).
    assert acct.get("id"), "Expected Alpaca /v2/account response to include an account id."
    assert acct.get("status"), "Expected Alpaca /v2/account response to include an account status."

    log_json(
        intent_type="alpaca_auth_smoke_test",
        severity="INFO",
        status="pass",
        check="rest_account",
        trading_host=env.trading_host,
        account_id=acct.get("id"),
        account_status=acct.get("status"),
    )


def test_alpaca_ws_auth_smoke_auth_only_no_subscriptions() -> None:
    """
    WebSocket smoke test:
    - Performs auth only
    - No subscriptions
    - No side effects
    """
    if not _should_run():
        pytest.skip("Set RUN_ALPACA_AUTH_SMOKE_TESTS=1 to enable Alpaca auth smoke tests.")
    if not _have_creds():
        pytest.skip("Missing Alpaca credentials (ALPACA_API_KEY/ALPACA_SECRET_KEY).")

    feed = (os.getenv("ALPACA_DATA_FEED") or "iex").strip().lower() or "iex"
    timeout_s = float(os.getenv("ALPACA_AUTH_SMOKE_TIMEOUT_S", "5"))
    asyncio.run(alpaca_ws_auth_smoke_test(feed=feed, timeout_s=timeout_s))

    ws_url = os.getenv("ALPACA_DATA_STREAM_WS_URL", "").strip() or f"wss://stream.data.alpaca.markets/v2/{feed}"
    log_json(
        intent_type="alpaca_auth_smoke_test",
        severity="INFO",
        status="pass",
        check="ws_auth_only",
        feed=feed,
        ws_url=ws_url,
    )

