from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from backend.persistence.firestore_retry import with_firestore_retry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    return int(v)


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


# Broker statuses (best-effort, normalized)
OPEN_STATUSES: frozenset[str] = frozenset(
    {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
        "replaced",
        "pending_replace",
        "pending_cancel",
    }
)

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "filled",
        "canceled",
        "cancelled",
        "expired",
        "rejected",
        "done_for_day",
    }
)


@dataclass(frozen=True, slots=True)
class TimeoutRules:
    """
    Timeout rules for "stuck" orders (defaults are conservative).

    Env overrides:
      - EXEC_ORDER_TIMEOUT_S_OPTIONS_MARKET (default: 20)
      - EXEC_ORDER_TIMEOUT_S_OPTIONS_LIMIT  (default: 120)
      - EXEC_ORDER_TIMEOUT_S_DEFAULT_MARKET (default: 15)
      - EXEC_ORDER_TIMEOUT_S_DEFAULT_LIMIT  (default: 90)
      - EXEC_ORDER_STALE_S                  (default: 60)
    """

    options_market_s: int = 20
    options_limit_s: int = 120
    default_market_s: int = 15
    default_limit_s: int = 90
    stale_s: int = 60

    @staticmethod
    def from_env() -> "TimeoutRules":
        return TimeoutRules(
            options_market_s=_int_env("EXEC_ORDER_TIMEOUT_S_OPTIONS_MARKET", 20),
            options_limit_s=_int_env("EXEC_ORDER_TIMEOUT_S_OPTIONS_LIMIT", 120),
            default_market_s=_int_env("EXEC_ORDER_TIMEOUT_S_DEFAULT_MARKET", 15),
            default_limit_s=_int_env("EXEC_ORDER_TIMEOUT_S_DEFAULT_LIMIT", 90),
            stale_s=_int_env("EXEC_ORDER_STALE_S", 60),
        )


def timeout_seconds_for_intent(*, asset_class: str, order_type: str, rules: TimeoutRules) -> int:
    asset = str(asset_class or "EQUITY").strip().upper()
    typ = _norm(order_type) or "market"
    is_limit_like = typ in {"limit", "stop_limit"}

    if asset == "OPTIONS":
        return int(rules.options_limit_s if is_limit_like else rules.options_market_s)
    return int(rules.default_limit_s if is_limit_like else rules.default_market_s)


def is_terminal_status(status: Any) -> bool:
    s = _norm(status)
    return bool(s in TERMINAL_STATUSES)


def is_open_status(status: Any) -> bool:
    s = _norm(status)
    return bool(s in OPEN_STATUSES)


def infer_asset_class(*, metadata: dict[str, Any] | None) -> str:
    """
    Infer asset class from metadata without changing external API.

    Accepted hints:
      - metadata.asset_class (e.g. "OPTIONS")
      - metadata.instrument_type (e.g. "option")
    """
    md = dict(metadata or {})
    ac = str(md.get("asset_class") or "").strip()
    if ac:
        return ac.strip().upper()
    inst = str(md.get("instrument_type") or "").strip().lower()
    if inst == "option" or inst == "options":
        return "OPTIONS"
    return "EQUITY"


@dataclass(frozen=True, slots=True)
class ExecutionOrderRecord:
    tenant_id: str
    client_intent_id: str
    broker_order_id: str | None
    status: str | None
    asset_class: str
    created_at: datetime | None
    last_broker_sync_at: datetime | None
    intent_snapshot: dict[str, Any]


class FirestoreExecutionOrderStore:
    """
    Minimal persistent store for broker orders created by the execution service.

    Collection:
      tenants/{tenant_id}/execution_orders/{client_intent_id}
    """

    def __init__(self, *, project_id: str | None = None, collection_name: str = "execution_orders") -> None:
        from backend.persistence.firebase_client import get_firestore_client

        self._db = get_firestore_client(project_id=project_id)
        self._collection_name = str(collection_name)

    def _ref(self, *, tenant_id: str, client_intent_id: str):
        return (
            self._db.collection("tenants")
            .document(str(tenant_id))
            .collection(self._collection_name)
            .document(str(client_intent_id))
        )

    def upsert(self, *, tenant_id: str, client_intent_id: str, payload: dict[str, Any]) -> None:
        ref = self._ref(tenant_id=tenant_id, client_intent_id=client_intent_id)
        with_firestore_retry(lambda: ref.set(payload, merge=True))

    def list_open(
        self,
        *,
        tenant_id: str,
        asset_class: str | None = None,
        limit: int = 50,
        statuses: Iterable[str] = OPEN_STATUSES,
    ) -> list[ExecutionOrderRecord]:
        tenant_id = str(tenant_id).strip()
        q = (
            self._db.collection("tenants")
            .document(tenant_id)
            .collection(self._collection_name)
            .where("status_norm", "in", list(dict.fromkeys([_norm(s) for s in statuses]))[:10])
        )
        if asset_class:
            q = q.where("asset_class", "==", str(asset_class).strip().upper())
        q = q.limit(int(max(1, min(500, limit))))

        out: list[ExecutionOrderRecord] = []
        for snap in with_firestore_retry(lambda: list(q.stream())):
            d = snap.to_dict() or {}
            out.append(
                ExecutionOrderRecord(
                    tenant_id=str(d.get("tenant_id") or tenant_id),
                    client_intent_id=str(d.get("client_intent_id") or snap.id),
                    broker_order_id=str(d.get("broker_order_id") or "").strip() or None,
                    status=str(d.get("status") or "").strip() or None,
                    asset_class=str(d.get("asset_class") or "EQUITY").strip().upper(),
                    created_at=d.get("created_at") if isinstance(d.get("created_at"), datetime) else None,
                    last_broker_sync_at=(
                        d.get("last_broker_sync_at") if isinstance(d.get("last_broker_sync_at"), datetime) else None
                    ),
                    intent_snapshot=dict(d.get("intent_snapshot") or {}),
                )
            )
        return out


def is_stale_for_poll(*, now: datetime, last_broker_sync_at: datetime | None, rules: TimeoutRules) -> bool:
    if last_broker_sync_at is None:
        return True
    return (now - last_broker_sync_at) >= timedelta(seconds=float(rules.stale_s))


def is_unfilled_past_timeout(*, now: datetime, created_at: datetime | None, timeout_s: int) -> bool:
    if created_at is None:
        return False
    return (now - created_at) >= timedelta(seconds=float(timeout_s))

