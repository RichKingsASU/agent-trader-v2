from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Tuple

from backend.common.idempotency import stable_uuid_from_key
from backend.common.logging import log_event
from backend.contracts.v2.trading import OptionOrderIntent
from backend.storage.shadow_option_trades import ShadowOptionTradeStore

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        try:
            return dict(asdict(value))
        except Exception:
            return {}
    fn = getattr(value, "to_dict", None)
    if callable(fn):
        try:
            out = fn()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    # Pydantic v2
    fn = getattr(value, "model_dump", None)
    if callable(fn):
        try:
            out = fn()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    return {}


def _detect_hold(intent: OptionOrderIntent) -> Optional[str]:
    """
    OptionOrderIntent has no explicit HOLD action, so we infer HOLD/NO-OP from metadata.
    """
    for container in (getattr(intent, "options", None), getattr(intent, "meta", None)):
        if not isinstance(container, Mapping):
            continue
        for k in ("action", "signal_action", "signalAction", "decision", "intent_action", "intentAction"):
            v = container.get(k)
            if v is None:
                continue
            s = str(v).strip().lower()
            if s in {"hold", "no_op", "noop", "none"}:
                return f"hold:{k}={s}"
    return None


def _parse_contracts(intent: OptionOrderIntent) -> Tuple[Optional[int], Optional[str]]:
    """
    Determine contract count from the intent.

    For options, we treat `quantity` as contract count (integer).
    """
    q_raw = getattr(intent, "quantity", None)
    if q_raw is None:
        return None, "missing_quantity_contracts"
    s = str(q_raw).strip()
    if not s:
        return None, "missing_quantity_contracts"
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None, "invalid_quantity_contracts"
    if d <= 0:
        return None, "non_positive_quantity_contracts"
    # Enforce integer contracts (e.g., "1", "2.0" ok; "1.5" rejected).
    if d != d.to_integral_value():
        return None, "non_integer_quantity_contracts"
    return int(d), None


def _resolve_option_symbol(*, intent: OptionOrderIntent, resolved_contract: Any) -> str:
    d = _as_dict(resolved_contract)
    for k in ("contract_symbol", "symbol", "option_symbol", "occ_symbol", "occSymbol"):
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    # Fall back to the intent contract symbol.
    return str(intent.contract_symbol).strip()


class ShadowOptionExecutor:
    """
    Shadow-only executor for option order intents.

    Hard constraints:
    - NEVER calls Alpaca (or any broker).
    - NEVER places real orders.
    - Restart-idempotent: same intent replay must not create duplicate shadow records.
    - Writes ONLY to `shadowTradeHistory` (via ShadowOptionTradeStore).
    """

    def __init__(self, *, store: ShadowOptionTradeStore | None = None, db: Any | None = None) -> None:
        self._store = store or ShadowOptionTradeStore(db=db)

    def execute(
        self,
        *,
        intent: OptionOrderIntent,
        resolved_contract: Any,
        reason: str = "shadow_only_execution",
        metadata_snapshot: Mapping[str, Any] | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Simulate execution and persist a single append-only record to shadowTradeHistory.

        Returns:
            {
              "applied": bool,  # True only when we created a new record
              "status": "simulated" | "skipped",
              "reason": str,
              "doc_id": str | None,
              "record": dict | None
            }
        """
        ts = now_utc or _utc_now()
        corr = str(getattr(intent, "correlation_id", None) or "").strip() or None

        opt_symbol = _resolve_option_symbol(intent=intent, resolved_contract=resolved_contract)
        side = str(getattr(intent, "side", "")).strip().lower()

        try:
            log_event(
                logger,
                "option.execution.attempt",
                severity="INFO",
                correlation_id=corr,
                tenant_id=intent.tenant_id,
                intent_id=str(intent.intent_id),
                option_symbol=opt_symbol,
                side=side,
                timestamp=ts.isoformat(),
            )
        except Exception:
            pass

        hold_reason = _detect_hold(intent)
        if hold_reason is not None:
            try:
                log_event(
                    logger,
                    "option.execution.skipped",
                    severity="INFO",
                    correlation_id=corr,
                    tenant_id=intent.tenant_id,
                    intent_id=str(intent.intent_id),
                    option_symbol=opt_symbol,
                    side=side,
                    reason=hold_reason,
                    timestamp=ts.isoformat(),
                )
            except Exception:
                pass
            return {"applied": False, "status": "skipped", "reason": hold_reason, "doc_id": None, "record": None}

        contracts, contracts_err = _parse_contracts(intent)
        if contracts is None:
            r = contracts_err or "missing_contracts"
            try:
                log_event(
                    logger,
                    "option.execution.skipped",
                    severity="WARNING",
                    correlation_id=corr,
                    tenant_id=intent.tenant_id,
                    intent_id=str(intent.intent_id),
                    option_symbol=opt_symbol,
                    side=side,
                    reason=r,
                    timestamp=ts.isoformat(),
                )
            except Exception:
                pass
            return {"applied": False, "status": "skipped", "reason": r, "doc_id": None, "record": None}

        # Stable doc id for restart idempotency (scoped by tenant + intent_id).
        doc_uuid = stable_uuid_from_key(key=f"{intent.tenant_id}:shadow_option_intent:{intent.intent_id}")
        doc_id = str(doc_uuid)

        # Snapshot: keep it small and stable. We always include the intent + resolved contract.
        snapshot: dict[str, Any] = {
            "intent": intent.model_dump(by_alias=True),
            "resolved_contract": _as_dict(resolved_contract),
        }
        if metadata_snapshot:
            snapshot["metadata"] = dict(metadata_snapshot)

        record, created = self._store.create_simulated_once(
            doc_id=doc_id,
            intent_id=intent.intent_id,
            option_symbol=opt_symbol,
            contracts=int(contracts),
            side=side,
            reason=str(reason),
            metadata_snapshot=snapshot,
            now_utc=ts,
        )

        if created:
            try:
                log_event(
                    logger,
                    "option.execution.simulated",
                    severity="INFO",
                    correlation_id=corr,
                    tenant_id=intent.tenant_id,
                    intent_id=str(intent.intent_id),
                    option_symbol=opt_symbol,
                    side=side,
                    contracts=int(contracts),
                    status="simulated",
                    reason=str(reason),
                    timestamp=ts.isoformat(),
                    doc_id=doc_id,
                )
            except Exception:
                pass
            return {"applied": True, "status": "simulated", "reason": str(reason), "doc_id": doc_id, "record": record}

        # Duplicate replay / restart: record already exists.
        dup_reason = "duplicate_intent_replay"
        try:
            log_event(
                logger,
                "option.execution.skipped",
                severity="INFO",
                correlation_id=corr,
                tenant_id=intent.tenant_id,
                intent_id=str(intent.intent_id),
                option_symbol=opt_symbol,
                side=side,
                reason=dup_reason,
                timestamp=ts.isoformat(),
                doc_id=doc_id,
            )
        except Exception:
            pass
        return {"applied": False, "status": "skipped", "reason": dup_reason, "doc_id": doc_id, "record": record}


__all__ = ["ShadowOptionExecutor"]

