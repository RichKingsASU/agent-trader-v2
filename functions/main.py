"""
Pulse: scheduled Alpaca account snapshot sync.

Every minute, fetch the Alpaca account and write it to:
  Firestore: alpacaAccounts/snapshot
"""

import logging
import os
from typing import Any, Dict

import alpaca_trade_api as tradeapi
import firebase_admin
from firebase_admin import firestore
from firebase_functions import scheduler_fn

from backend.config.alpaca_env import load_alpaca_auth_env

firebase_admin.initialize_app()
logger = logging.getLogger(__name__)


def _get_firestore() -> firestore.Client:
    return firestore.client()


def _get_alpaca() -> tradeapi.REST:
    auth = load_alpaca_auth_env()
    return tradeapi.REST(key_id=auth.api_key_id, secret_key=auth.api_secret_key, base_url=auth.api_base_url)


def _account_payload(account: Any) -> Dict[str, Any]:
    # alpaca-trade-api returns an Entity with a _raw dict.
    raw: Dict[str, Any]
    if hasattr(account, "_raw") and isinstance(account._raw, dict):  # type: ignore[attr-defined]
        raw = dict(account._raw)  # type: ignore[attr-defined]
    elif isinstance(account, dict):
        raw = dict(account)
    else:
        raw = {k: getattr(account, k) for k in dir(account) if not k.startswith("_")}

    # Preserve numeric precision by storing as strings.
    for k in ("equity", "buying_power", "cash"):
        if raw.get(k) is not None:
            raw[k] = str(raw[k])

    return {
        "syncedAt": firestore.SERVER_TIMESTAMP,
        "account": raw,
        "equity": raw.get("equity"),
        "buying_power": raw.get("buying_power"),
        "cash": raw.get("cash"),
    }


@scheduler_fn.on_schedule(schedule='* * * * *')
def sync_alpaca_account(event: scheduler_fn.ScheduledEvent) -> None:
    _ = event  # unused
    logger.info("sync_alpaca_account: syncing Alpaca account -> Firestore alpacaAccounts/snapshot")

    api = _get_alpaca()
    account = api.get_account()
    payload = _account_payload(account)

    db = _get_firestore()
    db.collection("alpacaAccounts").document("snapshot").set(payload, merge=True)
    logger.info("sync_alpaca_account: done")