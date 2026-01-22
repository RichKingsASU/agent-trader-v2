from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.common.env import (
    get_alpaca_api_base_url,
    get_alpaca_key_id,
    get_alpaca_secret_key,
)
from backend.common.agent_mode import AgentMode, get_agent_mode


@dataclass(frozen=True)
class ApcaEnv:
    api_key_id: str
    api_secret_key: str
    api_base_url: str


def _get_required(name: str) -> str:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v).strip()


def get_apca_env() -> ApcaEnv:
    """
    Load APCA_* env vars and normalize the base URL (strip trailing slash).
    """
    key_id = _get_required("APCA_API_KEY_ID")
    secret_key = _get_required("APCA_API_SECRET_KEY")
    base_url = _get_required("APCA_API_BASE_URL")
    base_url = base_url[:-1] if base_url.endswith("/") else base_url
    
    agent_mode = get_agent_mode()
    trading_mode = (os.getenv("TRADING_MODE") or "").strip().lower() or "paper"
    base_url = assert_valid_alpaca_base_url(
        url=base_url,
        agent_mode=agent_mode,
        trading_mode=trading_mode,
    )
    return ApcaEnv(api_key_id=key_id, api_secret_key=secret_key, api_base_url=base_url)


def assert_apca_env() -> None:
    """
    Fail fast at startup if APCA_* is missing.
    """
    _ = get_apca_env()


def assert_valid_alpaca_base_url(url: str, agent_mode: AgentMode, trading_mode: str) -> str:
    """
    Safety boundary: Validate Alpaca API base URLs based on the current
    AGENT_MODE and TRADING_MODE.

    Allowed:
    - https://paper-api.alpaca.markets when AGENT_MODE is not LIVE, or TRADING_MODE='paper'
    - https://api.alpaca.markets when AGENT_MODE=LIVE and TRADING_MODE='live'

    Forbidden (hard fail):
    - Any host not explicitly allowed for the given mode.
    - Any scheme other than https.
    - Any URL including credentials (username/password), query, or fragment.
    """
    if url is None or str(url).strip() == "":
        raise RuntimeError("Missing required Alpaca base URL (APCA_API_BASE_URL)")

    raw = str(url).strip()
    lowered = raw.lower()

    # --- Scheme and URL component validation (universal rules) ---
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeError(f"REFUSED: Alpaca base URL must be https: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"REFUSED: Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"REFUSED: Alpaca base URL must not include query/fragment: {raw!r}")

    # --- Hostname validation (mode-specific rules) ---
    hostname = (parsed.hostname or "").lower()

    # Paper mode explicit check
    if trading_mode == "paper":
        if hostname == "paper-api.alpaca.markets":
            # Normalize (preserve any path; just strip trailing slash).
            return raw[:-1] if raw.endswith("/") else raw
        raise RuntimeError(
            "REFUSED: TRADING_MODE='paper' requires Alpaca base URL to be 'https://paper-api.alpaca.markets'. "
            f"Got: {raw!r}"
        )
    
    # Live mode explicit check (only if AgentMode is LIVE)
    elif trading_mode == "live" and agent_mode == AgentMode.LIVE:
        if hostname == "api.alpaca.markets":
            # Normalize
            return raw[:-1] if raw.endswith("/") else raw
        else:
            raise RuntimeError(
                f"REFUSED: AGENT_MODE='LIVE' and TRADING_MODE='live' requires Alpaca base URL "
                f"to be 'https://api.alpaca.markets'. Got: {raw!r}"
            )

    # If neither paper nor live (e.g. AGENT_MODE=OBSERVE or AGENT_MODE=WARMUP)
    # and not explicitly handled above, we reject.
    raise RuntimeError(
        f"REFUSED: Alpaca base URL validation failed for mode '{agent_mode.value}' "
        f"and trading_mode '{trading_mode}'. Got: {raw!r}"
    )

