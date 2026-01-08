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

firebase_admin.initialize_app()
logger = logging.getLogger(__name__)

from functions.utils.apca_env import get_apca_env


def _get_firestore() -> firestore.Client:
    return firestore.client()


def _get_alpaca() -> tradeapi.REST:
    apca = get_apca_env()
    return tradeapi.REST(
        key_id=apca.api_key_id,
        secret_key=apca.api_secret_key,
        base_url=apca.api_base_url,
    )


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

    # Persist an equity time-series point for rolling risk metrics (drawdown velocity).
    # Store at: alpacaAccounts/snapshot/equity_history/{YYYYMMDDHHMM}
    try:
        equity = payload.get("equity")
        if equity is not None and str(equity).strip() != "":
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            doc_id = now.strftime("%Y%m%d%H%M")  # one point per minute
            db.collection("alpacaAccounts").document("snapshot").collection("equity_history").document(doc_id).set(
                {
                    "ts": firestore.SERVER_TIMESTAMP,
                    "equity": str(equity),
                },
                merge=True,
            )
    except Exception as e:
        # Best-effort only; never block snapshot sync.
        logger.warning("sync_alpaca_account: failed to write equity_history point: %s", e)

    logger.info("sync_alpaca_account: done")