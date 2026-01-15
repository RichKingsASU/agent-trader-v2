from __future__ import annotations

import os
from typing import Any


def get_env(name: str, *, default: Any = None, required: bool = False) -> str | None:
    """
    Read a runtime env var (non-secret contract).

    Safety behavior:
    - If required=True and missing/blank -> raise RuntimeError
    - Otherwise return stripped value or default
    """
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return None if default is None else str(default)
    return str(v).strip()


# ---------------------------------------------------------------------------
# Alpaca env helpers (official Alpaca SDK env vars)
# ---------------------------------------------------------------------------
#
# NOTE:
# - In CI/unit tests we rely on env injection (monkeypatch.setenv).
# - In production these may be injected from Secret Manager by the runtime.
# - This module is an allowed boundary for reading APCA_* at runtime.


def get_alpaca_key_id(*, required: bool = False) -> str | None:
    return get_env("APCA_API_KEY_ID", required=required)


def get_alpaca_api_key(*, required: bool = False) -> str | None:
    # Alias used by some modules.
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = False) -> str | None:
    return get_env("APCA_API_SECRET_KEY", required=required)


def get_alpaca_api_base_url(*, required: bool = False) -> str | None:
    # Default is paper (safety-first).
    v = get_env("APCA_API_BASE_URL", required=required)
    if v is None:
        return None
    return v[:-1] if v.endswith("/") else v

