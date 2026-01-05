from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests
from google.cloud import firestore

from backend.common.env import get_alpaca_api_key, get_alpaca_secret_key
from backend.persistence.firestore_retry import with_firestore_retry
from backend.persistence.firebase_client import get_firestore_client


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(v: Any) -> float:
    """
    Alpaca account fields are often strings; normalize to float.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError as e:
            raise ValueError(f"Expected numeric string, got {v!r}") from e
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def syncAlpacaAccount(
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    alpaca_trading_host: str | None = None,
    alpaca_api_key: str | None = None,
    alpaca_secret_key: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """
    Fetch the current Alpaca trading account snapshot and persist key fields to Firestore.

    Firestore paths:
      - Tenant-scoped (legacy): tenants/{tenant_id}/accounts/primary
      - User-scoped (multi-tenant): users/{user_id}/alpacaAccounts/snapshot

    Stored fields (required by frontend):
      - equity (number)
      - buying_power (number)
      - cash (number)

    Auth:
    - Uses Firebase Admin SDK (python `firebase-admin`) via ADC (see `backend.persistence.firebase_client`).
    - Alpaca creds are read from env via `os.getenv` (through `backend.common.env`):
      - ALPACA_API_KEY (preferred) or ALPACA_KEY_ID (back-compat)
      - ALPACA_SECRET_KEY
      
    Args:
        tenant_id: Tenant ID for legacy tenant-scoped path
        user_id: User ID for multi-tenant user-scoped path (recommended for new code)
        alpaca_trading_host: Alpaca API host URL
        alpaca_api_key: Alpaca API key
        alpaca_secret_key: Alpaca secret key
        timeout_s: Request timeout in seconds
    """
    resolved_tenant_id = (tenant_id or os.getenv("TENANT_ID") or "").strip() or "local"
    resolved_user_id = (user_id or os.getenv("USER_ID") or "").strip()

    trading_host = (alpaca_trading_host or os.getenv("ALPACA_TRADING_HOST") or "").strip()
    if not trading_host:
        trading_host = "https://paper-api.alpaca.markets"
    trading_host = trading_host[:-1] if trading_host.endswith("/") else trading_host

    key = (alpaca_api_key or get_alpaca_api_key(required=True)).strip()
    sec = (alpaca_secret_key or get_alpaca_secret_key(required=True)).strip()

    url = f"{trading_host}/v2/account"
    r = requests.get(
        url,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
        timeout=timeout_s,
    )
    r.raise_for_status()
    acct = r.json() or {}

    payload: dict[str, Any] = {
        "broker": "alpaca",
        "external_account_id": acct.get("id"),
        "status": acct.get("status"),
        "equity": _as_float(acct.get("equity")),
        "buying_power": _as_float(acct.get("buying_power")),
        "cash": _as_float(acct.get("cash")),
        "updated_at": firestore.SERVER_TIMESTAMP,
        "updated_at_iso": _utc_now().isoformat(),
        # keep the raw payload for debugging; do not include secrets
        "raw": acct,
    }

    db = get_firestore_client()
    
    # Write to tenant-scoped path (legacy support)
    doc_ref = db.collection("tenants").document(resolved_tenant_id).collection("accounts").document("primary")
    with_firestore_retry(lambda: doc_ref.set(payload, merge=True))

    # Write to user-scoped path (multi-tenant)
    if resolved_user_id:
        user_payload = dict(payload)
        user_payload["user_id"] = resolved_user_id
        user_ref = db.collection("users").document(resolved_user_id).collection("alpacaAccounts").document("snapshot")
        with_firestore_retry(lambda: user_ref.set(user_payload, merge=True))
    else:
        # Legacy: also write to global warm-cache for backward compatibility
        warm_cache_payload = dict(payload)
        warm_cache_payload["tenant_id"] = resolved_tenant_id
        warm_cache_ref = db.collection("alpacaAccounts").document("snapshot")
        with_firestore_retry(lambda: warm_cache_ref.set(warm_cache_payload, merge=True))
        
    return payload

