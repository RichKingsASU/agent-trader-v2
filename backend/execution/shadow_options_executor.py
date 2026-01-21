from __future__ import annotations

"""
SHADOW options execution (simulation only).

Constraints:
- No broker calls
- No interaction with execution_service, brokers, or Alpaca SDKs
- Full-fill only (no partial fills)
- Fill price = mid ± fixed slippage (configurable, constant)
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from google.api_core import exceptions as gexc
from google.cloud import firestore

from backend.common.logging import log_event
from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.trading.execution.models import ExecutionDecision

from .fill_models import (
    OptionOrderIntent,
    ShadowExecutionAttempt,
    ShadowExecutionCompleted,
    ShadowOptionPosition,
    ShadowOptionTrade,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _stable_id(*, scope: str, key: str) -> str:
    raw = f"{scope}|{key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:48]


def _position_key(intent: OptionOrderIntent) -> str:
    # Keep a stable, opaque key; callers can embed richer metadata in intent.metadata if needed.
    return f"{intent.symbol.upper()}|{intent.option_symbol.upper()}"


def _simulate_fill_price(*, side: str, mid: float, slippage_abs: float) -> float:
    slip = max(0.0, float(slippage_abs))
    if str(side).upper() == "BUY":
        return float(mid) + slip
    # SELL
    return max(0.0, float(mid) - slip)


def _read_position_doc(*, db: Any, uid: str, position_id: str) -> Optional[dict[str, Any]]:
    ref = db.collection("users").document(uid).collection("shadowOptionPositions").document(position_id)
    snap = with_firestore_retry(lambda: ref.get())
    if not getattr(snap, "exists", False):
        return None
    try:
        d = snap.to_dict() or {}
    except Exception:
        d = {}
    return d if isinstance(d, dict) else None


def _apply_position_update(
    *,
    prev: Optional[dict[str, Any]],
    intent: OptionOrderIntent,
    fill_price: float,
    now: datetime,
    position_id: str,
    position_key: str,
) -> Tuple[Optional[ShadowOptionPosition], Optional[dict[str, Any]]]:
    """
    Returns:
    - new ShadowOptionPosition (or None if closed)
    - firestore write payload (or None if delete)
    """
    delta = int(intent.quantity) if intent.side == "BUY" else -int(intent.quantity)

    prev_qty = 0
    prev_entry = None
    prev_opened = None
    if isinstance(prev, dict):
        try:
            prev_qty = int(prev.get("quantity") or 0)
        except Exception:
            prev_qty = 0
        try:
            prev_entry = float(prev.get("entry_price")) if prev.get("entry_price") is not None else None
        except Exception:
            prev_entry = None
        try:
            opened_raw = prev.get("opened_at_utc")
            if isinstance(opened_raw, datetime):
                prev_opened = opened_raw.astimezone(timezone.utc)
            elif isinstance(opened_raw, str) and opened_raw.strip():
                s = opened_raw.strip().replace("Z", "+00:00")
                prev_opened = datetime.fromisoformat(s).astimezone(timezone.utc)
        except Exception:
            prev_opened = None

    new_qty = prev_qty + delta
    if new_qty == 0:
        return None, None

    # Decide whether this is a new/flip position.
    is_new_or_flip = (prev_qty == 0) or ((prev_qty > 0) != (new_qty > 0))

    if is_new_or_flip or prev_entry is None:
        entry_price = float(fill_price)
        opened_at = now
    else:
        opened_at = prev_opened or now
        # If increasing exposure in same direction, update weighted-average entry.
        increasing = abs(new_qty) > abs(prev_qty)
        if increasing:
            added = abs(delta)
            base = abs(prev_qty)
            denom = float(base + added)
            entry_price = ((float(prev_entry) * float(base)) + (float(fill_price) * float(added))) / denom if denom > 0 else float(fill_price)
        else:
            # Reducing exposure: keep entry price.
            entry_price = float(prev_entry)

    pos = ShadowOptionPosition(
        position_id=position_id,
        position_key=position_key,
        tenant_id=intent.tenant_id,
        uid=intent.uid,
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        quantity=int(new_qty),
        entry_price=float(entry_price),
        opened_at_utc=opened_at,
        updated_at_utc=now,
    )
    payload = pos.model_dump()
    # Firestore-friendly timestamps (explicit)
    payload["last_updated"] = firestore.SERVER_TIMESTAMP
    return pos, payload


def execute_shadow_option(
    *,
    intent: OptionOrderIntent,
    risk_decision: ExecutionDecision,
    slippage_abs: float | None = None,
    db: Any | None = None,
    log: logging.Logger | None = None,
) -> ShadowOptionTrade:
    """
    Simulate a single, full options fill and update shadow position state.

    Writes:
    - users/{uid}/shadowOptionTradeHistory/{trade_id}
    - users/{uid}/shadowOptionPositions/{position_id} (upsert/delete)

    Emits (structured logs only):
    - execution.attempt (mode=shadow)
    - execution.completed (mode=shadow)
    """
    lg = log or logger
    if getattr(risk_decision, "decision", None) != "APPROVE":
        raise ValueError("risk_decision must be APPROVE for shadow execution")

    now = _utc_now()
    slip = float(slippage_abs) if slippage_abs is not None else _env_float("SHADOW_OPTIONS_SLIPPAGE_ABS", 0.02)
    mid = float(intent.mid_price or 0.0)
    if mid <= 0:
        raise ValueError("intent.mid_price must be > 0")

    fill_price = _simulate_fill_price(side=intent.side, mid=mid, slippage_abs=slip)

    # Stable identifiers for replay safety.
    position_key = _position_key(intent)
    position_id = _stable_id(scope="shadow_option_position", key=position_key)
    idem = (intent.idempotency_key or "").strip() or (intent.correlation_id or "").strip() or None
    trade_key = f"{idem or ''}|{position_key}|{intent.side}|{int(intent.quantity)}"
    trade_id = _stable_id(scope="shadow_option_trade", key=trade_key) if idem else _stable_id(scope="shadow_option_trade", key=f"{position_key}|{now.isoformat()}")

    # Emit attempt (shadow)
    attempt = ShadowExecutionAttempt(
        correlation_id=intent.correlation_id,
        execution_id=intent.execution_id,
        tenant_id=intent.tenant_id,
        uid=intent.uid,
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        side=intent.side,
        quantity=int(intent.quantity),
    )
    try:
        log_event(
            lg,
            "execution.attempt",
            severity="INFO",
            mode="shadow",
            correlation_id=intent.correlation_id,
            execution_id=intent.execution_id,
            tenant_id=intent.tenant_id,
            uid=intent.uid,
            instrument_type="option",
            symbol=intent.symbol,
            option_symbol=intent.option_symbol,
            side=intent.side,
            quantity=int(intent.quantity),
        )
    except Exception:
        pass

    # Firestore writes (trade + position)
    firestore_db = db or get_firestore_client()
    trade_ref = (
        firestore_db.collection("users")
        .document(intent.uid)
        .collection("shadowOptionTradeHistory")
        .document(trade_id)
    )

    # Position update
    prev_pos = _read_position_doc(db=firestore_db, uid=intent.uid, position_id=position_id)
    new_pos, pos_payload = _apply_position_update(
        prev=prev_pos,
        intent=intent,
        fill_price=fill_price,
        now=now,
        position_id=position_id,
        position_key=position_key,
    )

    # Write the trade record idempotently.
    trade_doc = {
        "trade_id": trade_id,
        "idempotency_key": idem,
        "tenant_id": intent.tenant_id,
        "uid": intent.uid,
        "strategy_id": intent.strategy_id,
        "correlation_id": intent.correlation_id,
        "execution_id": intent.execution_id,
        "symbol": intent.symbol,
        "option_symbol": intent.option_symbol,
        "side": intent.side,
        "quantity": int(intent.quantity),
        "mid_price": float(mid),
        "slippage_abs": float(slip),
        "fill_price": float(fill_price),
        "filled_at_utc": now.isoformat(),
        "position_id": position_id,
        "position_key": position_key,
        "risk_decision_id": getattr(risk_decision, "decision_id", None),
        "risk_proposal_id": getattr(risk_decision, "proposal_id", None),
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_at_iso": now.isoformat(),
    }
    try:
        with_firestore_retry(lambda: trade_ref.create(trade_doc))
    except gexc.AlreadyExists:
        snap = with_firestore_retry(lambda: trade_ref.get())
        if getattr(snap, "exists", False):
            # Keep idempotent: prefer stored trade doc
            trade_doc = snap.to_dict() or trade_doc

    # Upsert/delete position doc based on new_qty
    pos_ref = (
        firestore_db.collection("users")
        .document(intent.uid)
        .collection("shadowOptionPositions")
        .document(position_id)
    )
    if new_pos is None:
        try:
            with_firestore_retry(lambda: pos_ref.delete())
        except Exception:
            pass
    else:
        try:
            if pos_payload is None:
                pos_payload = new_pos.model_dump()
                pos_payload["last_updated"] = firestore.SERVER_TIMESTAMP
            with_firestore_retry(lambda: pos_ref.set(pos_payload, merge=True))
        except Exception:
            pass

    completed = ShadowExecutionCompleted(
        correlation_id=intent.correlation_id,
        execution_id=intent.execution_id,
        tenant_id=intent.tenant_id,
        uid=intent.uid,
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        side=intent.side,
        quantity=int(intent.quantity),
        trade_id=trade_id,
        position_id=position_id,
        fill_price=float(fill_price),
        slippage_abs=float(slip),
    )
    try:
        log_event(
            lg,
            "execution.completed",
            severity="INFO",
            mode="shadow",
            correlation_id=intent.correlation_id,
            execution_id=intent.execution_id,
            tenant_id=intent.tenant_id,
            uid=intent.uid,
            instrument_type="option",
            symbol=intent.symbol,
            option_symbol=intent.option_symbol,
            side=intent.side,
            quantity=int(intent.quantity),
            trade_id=trade_id,
            position_id=position_id,
            fill_price=float(fill_price),
            slippage_abs=float(slip),
        )
    except Exception:
        pass

    return ShadowOptionTrade(
        trade_id=trade_id,
        tenant_id=intent.tenant_id,
        uid=intent.uid,
        correlation_id=intent.correlation_id,
        execution_id=intent.execution_id,
        idempotency_key=idem,
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        side=intent.side,
        quantity=int(intent.quantity),
        mid_price=float(mid),
        slippage_abs=float(slip),
        fill_price=float(fill_price),
        filled_at_utc=now,
        position_id=position_id,
        position_key=position_key,
        risk_decision_id=getattr(risk_decision, "decision_id", None),
        risk_proposal_id=getattr(risk_decision, "proposal_id", None),
        execution_attempt=attempt,
        execution_completed=completed,
    )

