"""
Backward-compatible import path for Alpaca env loading used by backend streamers.

All logic lives in `backend.config.alpaca_env` (single shared helper).
"""

from __future__ import annotations

from backend.config.alpaca_env import AlpacaEnv, load_alpaca_env as _load


def load_alpaca_env(*, require_keys: bool = True) -> AlpacaEnv:
    """
    Backward-compatible signature for older stream modules.

    `require_keys` is ignored: credentials are always required and missing env
    vars fail fast.
    """
    _ = require_keys
    return _load()

__all__ = ["AlpacaEnv", "load_alpaca_env"]

