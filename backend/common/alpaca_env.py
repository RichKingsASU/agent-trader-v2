from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.common.secrets import SecretError, get_secret


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


@dataclass(frozen=True)
class AlpacaSecrets:
    api_key_id: str
    api_secret_key: str
    api_base_url: str
    mode: str


def _mode() -> str:
    # Repo policy is paper-first; treat missing as paper.
    return str(os.getenv("TRADING_MODE") or "paper").strip().lower() or "paper"


def _paper_or_live_base_url(mode: str) -> str:
    if mode == "live":
        return LIVE_BASE_URL
    return PAPER_BASE_URL


def _assert_paper_base_url(url: str) -> str:
    """
    Safety boundary for paper mode: only allow the Alpaca paper host over https.
    """
    raw = str(url or "").strip()
    if not raw:
        raise RuntimeError("Missing Alpaca base URL")
    parsed = urlparse(raw)
    if (parsed.scheme or "").lower() != "https":
        raise RuntimeError(f"Alpaca base URL must be https: {raw!r}")
    host = (parsed.hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise RuntimeError(f"Alpaca base URL must be paper host in paper mode: {raw!r}")
    if parsed.port not in (None, 443):
        raise RuntimeError(f"Alpaca base URL must not specify a port: {raw!r}")
    if parsed.username or parsed.password:
        raise RuntimeError(f"Alpaca base URL must not include credentials: {raw!r}")
    if parsed.query or parsed.fragment:
        raise RuntimeError(f"Alpaca base URL must not include query/fragment: {raw!r}")
    return raw[:-1] if raw.endswith("/") else raw


def configure_alpaca_env(*, required: bool = True) -> AlpacaSecrets:
    """
    Configure Alpaca SDK-compatible environment variables from Secret Manager.

    Outputs (for SDK compatibility):
    - APCA_API_KEY_ID
    - APCA_API_SECRET_KEY
    - APCA_API_BASE_URL

    Secret naming convention (by TRADING_MODE):
    - paper:
      - ALPACA_PAPER_API_KEY_ID
      - ALPACA_PAPER_API_SECRET_KEY
      - (optional) ALPACA_PAPER_API_BASE_URL  (defaults to https://paper-api.alpaca.markets)
    - live:
      - ALPACA_LIVE_API_KEY_ID
      - ALPACA_LIVE_API_SECRET_KEY
      - (optional) ALPACA_LIVE_API_BASE_URL   (defaults to https://api.alpaca.markets)

    Notes:
    - Env var fallback is allowed only when ALLOW_ENV_SECRET_FALLBACK=1 (see secrets.py).
    - This function *sets* APCA_* in-process to keep downstream Alpaca SDKs working
      without requiring shell exports.
    """
    mode = _mode()
    if mode not in {"paper", "live"}:
        # Stay strict to avoid ambiguous secret routing.
        raise RuntimeError(f"Invalid TRADING_MODE for Alpaca secrets routing: {mode!r} (expected 'paper' or 'live')")

    if mode == "live":
        key_id_secret = "ALPACA_LIVE_API_KEY_ID"
        secret_key_secret = "ALPACA_LIVE_API_SECRET_KEY"
        base_url_secret = "ALPACA_LIVE_API_BASE_URL"
    else:
        key_id_secret = "ALPACA_PAPER_API_KEY_ID"
        secret_key_secret = "ALPACA_PAPER_API_SECRET_KEY"
        base_url_secret = "ALPACA_PAPER_API_BASE_URL"

    api_key_id = get_secret(key_id_secret, required=required)
    api_secret_key = get_secret(secret_key_secret, required=required)

    # Base URL isn't a secret, but allow secret-managed override for parity with other deployment config.
    api_base_url = get_secret(base_url_secret, required=False) or _paper_or_live_base_url(mode)

    if required:
        if not api_key_id or not str(api_key_id).strip():
            raise SecretError(f"Missing required Alpaca secret: {key_id_secret}")
        if not api_secret_key or not str(api_secret_key).strip():
            raise SecretError(f"Missing required Alpaca secret: {secret_key_secret}")

    # Normalize and set APCA_* for SDK compatibility.
    os.environ["APCA_API_KEY_ID"] = str(api_key_id or "").strip()
    os.environ["APCA_API_SECRET_KEY"] = str(api_secret_key or "").strip()
    os.environ["APCA_API_BASE_URL"] = str(api_base_url or "").strip().rstrip("/")

    # Safety: in paper mode, ensure we didn't accidentally set a live host.
    if mode != "live":
        os.environ["APCA_API_BASE_URL"] = _assert_paper_base_url(os.environ["APCA_API_BASE_URL"])

    return AlpacaSecrets(
        api_key_id=os.environ.get("APCA_API_KEY_ID", ""),
        api_secret_key=os.environ.get("APCA_API_SECRET_KEY", ""),
        api_base_url=os.environ.get("APCA_API_BASE_URL", ""),
        mode=mode,
    )

