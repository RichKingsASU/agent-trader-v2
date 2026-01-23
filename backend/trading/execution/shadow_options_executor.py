from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from backend.common.idempotency import stable_uuid_from_key
from backend.contracts.v2.trading import OptionOrderIntent

logger = logging.getLogger(__name__)


class ShadowTradeHistoryStore(Protocol):
    """
    Persistence boundary for shadow trade history.

    IMPORTANT:
    - The executor must remain I/O-free (no network calls). Any persistence is done
      through this injected interface.
    """

    def create_or_get(self, *, shadow_id: str, record: Mapping[str, Any]) -> Mapping[str, Any]: ...


class InMemoryShadowTradeHistoryStore:
    """
    Hermetic in-memory store for unit tests and local development.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    @property
    def items(self) -> dict[str, dict[str, Any]]:
        return self._items

    def create_or_get(self, *, shadow_id: str, record: Mapping[str, Any]) -> Mapping[str, Any]:
        if shadow_id not in self._items:
            self._items[shadow_id] = dict(record)
        return dict(self._items[shadow_id])


def _quantize_4(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.0001")))


def _derive_option_entry_price(*, notional: str | None, quantity: str | None, limit_price: str | None) -> str:
    """
    Shadow-only fill price derivation for options without market/broker calls.

    Priority:
    - use intent.limit_price if present (already a per-contract premium)
    - else, if notional and quantity present: premium per contract = notional / (quantity * 100)
    - else: "0"
    """
    try:
        if limit_price and str(limit_price).strip():
            lp = Decimal(str(limit_price).strip())
            return _quantize_4(lp) if lp > 0 else "0"
    except (InvalidOperation, ValueError):
        pass

    try:
        if not (notional and quantity):
            return "0"
        n = Decimal(str(notional).strip())
        q = Decimal(str(quantity).strip())
        if n <= 0 or q <= 0:
            return "0"
        # Options multiplier default: 100.
        return _quantize_4(n / (q * Decimal("100")))
    except (InvalidOperation, ValueError):
        return "0"


@dataclass(frozen=True)
class ShadowOptionsExecutionResult:
    status: str
    shadow_id: str
    stored: Mapping[str, Any]


class ShadowOptionsExecutor:
    """
    Shadow executor for options:
    - accepts OptionOrderIntent
    - logs the intent
    - stores a shadow trade record in shadowTradeHistory via injected store
    - never contacts any broker (no Alpaca)
    - never performs network I/O directly
    - always returns status="simulated"
    """

    def __init__(self, *, store: ShadowTradeHistoryStore) -> None:
        self._store = store

    def execute(self, *, intent: OptionOrderIntent) -> ShadowOptionsExecutionResult:
        # Log (safe JSON shape).
        try:
            logger.info(
                "shadow_options_executor.intent %s",
                intent.model_dump(mode="json"),
            )
        except Exception:
            logger.info("shadow_options_executor.intent (unserializable)")

        shadow_id = str(stable_uuid_from_key(key=f"shadowTradeHistory:option:{intent.intent_id}"))

        # Best-effort metadata extraction (optional; used by UIs / tenancy scoping).
        opt = intent.options or {}
        meta = getattr(intent, "meta", None) or {}
        uid = opt.get("uid") or opt.get("user_id") or opt.get("userId") or meta.get("uid") or meta.get("user_id") or meta.get("userId")
        tenant_id = str(getattr(intent, "tenant_id", "") or "").strip() or None

        entry_price = _derive_option_entry_price(
            notional=getattr(intent, "notional", None),
            quantity=getattr(intent, "quantity", None),
            limit_price=getattr(intent, "limit_price", None),
        )

        record: dict[str, Any] = {
            # Canonical ids
            "shadow_id": shadow_id,
            "intent_id": str(intent.intent_id),
            # Tenancy/user (optional)
            "uid": str(uid) if uid is not None and str(uid).strip() else None,
            "tenant_id": tenant_id,
            # Intent fields
            "account_id": str(intent.account_id),
            "strategy_id": str(intent.strategy_id) if intent.strategy_id else None,
            "symbol": str(intent.symbol),
            "asset_class": str(intent.asset_class.value if hasattr(intent.asset_class, "value") else intent.asset_class),
            "instrument_type": "option",
            "side": str(intent.side.value if hasattr(intent.side, "value") else intent.side).upper(),
            "order_type": str(intent.order_type.value if hasattr(intent.order_type, "value") else intent.order_type),
            "time_in_force": str(intent.time_in_force.value if hasattr(intent.time_in_force, "value") else intent.time_in_force),
            "quantity": getattr(intent, "quantity", None),
            "notional": getattr(intent, "notional", None),
            "limit_price": getattr(intent, "limit_price", None),
            # Option contract identity
            "contract_symbol": str(intent.contract_symbol),
            "expiration": intent.expiration.isoformat(),
            "strike": str(intent.strike),
            "right": str(intent.right),
            # Shadow fill fields (no market/broker calls)
            "entry_price": entry_price,
            "current_price": entry_price,
            "current_pnl": "0.00",
            "pnl_percent": "0.00",
            # Status fields
            # - `status` aligns with existing shadow PnL pipelines (OPEN/CLOSED)
            # - `execution_status` matches the executor contract (simulated)
            "status": "OPEN",
            "execution_status": "simulated",
            "mode": "shadow",
            # Timestamps (iso only; store implementations can add server timestamps)
            "created_at_iso": datetime.now(timezone.utc).isoformat(),
        }
        # Strip None for cleaner documents.
        record = {k: v for (k, v) in record.items() if v is not None}

        stored = self._store.create_or_get(shadow_id=shadow_id, record=record)
        return ShadowOptionsExecutionResult(status="simulated", shadow_id=shadow_id, stored=stored)

