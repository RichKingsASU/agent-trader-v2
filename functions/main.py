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
from firebase_functions import https_fn, options, scheduler_fn

firebase_admin.initialize_app()
logger = logging.getLogger(__name__)

from functions.utils.apca_env import get_apca_env
from risk_manager import update_risk_state


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


@https_fn.on_call(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["POST"]),
    secrets=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"],
)
def emergency_liquidate(req: https_fn.CallableRequest) -> Dict[str, Any]:
    """
    Kill-switch: cancel all orders, close all positions, and disable trading.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required",
        )

    db = _get_firestore()

    # Fail-closed first: disable trading gate + mark system halt.
    db.collection("systemStatus").document("risk").set(
        {
            "trading_enabled": False,
            "reason": "emergency_liquidate",
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    db.collection("systemStatus").document("system").set(
        {
            "state": "EMERGENCY_HALT",
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    orders_canceled = 0
    positions_closed = 0

    try:
        api = _get_alpaca()

        try:
            canceled = api.cancel_all_orders()
            if isinstance(canceled, list):
                orders_canceled = len(canceled)
        except Exception as e:  # noqa: BLE001
            logger.warning("emergency_liquidate: cancel_all_orders failed: %s", e)

        try:
            closed = api.close_all_positions()
            if isinstance(closed, list):
                positions_closed = len(closed)
        except Exception as e:  # noqa: BLE001
            logger.warning("emergency_liquidate: close_all_positions failed: %s", e)

        return {
            "success": True,
            "message": "Emergency liquidation executed; trading halted.",
            "positions_closed": positions_closed,
            "orders_canceled": orders_canceled,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("emergency_liquidate failed: %s", e)
        return {
            "success": False,
            "message": f"Emergency liquidation encountered an error: {e}",
            "positions_closed": positions_closed,
            "orders_canceled": orders_canceled,
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

    # Update risk state (HWM/drawdown + trading gate) as part of the pulse.
    try:
        eq = payload.get("equity") or "0"
        bp = payload.get("buying_power")
        update_risk_state(current_equity=str(eq), buying_power=(str(bp) if bp is not None else None), db=db)
    except Exception as e:  # noqa: BLE001
        logger.warning("sync_alpaca_account: update_risk_state failed (best-effort): %s", e)

    logger.info("sync_alpaca_account: done")
