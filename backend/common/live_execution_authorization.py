from __future__ import annotations

import os

from backend.common.execution_confirm import require_confirm_token_for_live_execution


class LiveExecutionAuthorizationError(RuntimeError):
    """
    Raised when a caller attempts to authorize live trading without satisfying
    all explicit authorization conditions.
    """


def assert_live_execution_authorized(
    *,
    provided_confirm_token: str | None,
    agent_mode: str | None = None,
    trading_mode: str | None = None,
    alpaca_api_base_url: str | None = None,
) -> None:
    """
    Prove-by-assertion gate: live execution must be impossible without explicit authorization.

    Required conditions (fail closed):
    - AGENT_MODE == LIVE
    - TRADING_MODE == live
    - EXECUTION_CONFIRM_TOKEN exists and matches provided_confirm_token
    - If TRADING_MODE=paper, APCA_API_BASE_URL must be paper host; a live Alpaca URL in paper mode is refused

    Notes:
    - This function is intentionally strict and explicit so tests can assert the exact refusal reasons.
    - It does not place orders; it only authorizes *eligibility* for live execution.
    """

    am = str(agent_mode if agent_mode is not None else (os.getenv("AGENT_MODE") or "")).strip().upper()
    if am != "LIVE":
        raise LiveExecutionAuthorizationError(f"AGENT_MODE!=LIVE (got {am or 'MISSING'})")

    tm = str(trading_mode if trading_mode is not None else (os.getenv("TRADING_MODE") or "")).strip().lower()
    base_url = str(
        alpaca_api_base_url if alpaca_api_base_url is not None else (os.getenv("APCA_API_BASE_URL") or "")
    ).strip()

    # Explicit mismatch protection called out in the task:
    # Live API URL + paper mode => FAIL.
    if tm == "paper" and "api.alpaca.markets" in base_url and "paper-api.alpaca.markets" not in base_url:
        raise LiveExecutionAuthorizationError("Live Alpaca API URL is forbidden when TRADING_MODE=paper")

    if tm != "live":
        raise LiveExecutionAuthorizationError(f"TRADING_MODE!=live (got {tm or 'MISSING'})")

    if not base_url:
        # Live execution requires an explicit broker endpoint selection; avoid "mystery default" live execution.
        raise LiveExecutionAuthorizationError("Missing APCA_API_BASE_URL (required for live authorization)")

    # Defense: ensure we aren't accidentally pointing at paper while claiming live mode.
    if "paper-api.alpaca.markets" in base_url:
        raise LiveExecutionAuthorizationError("Paper Alpaca API URL is forbidden when TRADING_MODE=live")

    # Token gate (fail-closed if expected token missing/empty).
    require_confirm_token_for_live_execution(provided_token=provided_confirm_token)

