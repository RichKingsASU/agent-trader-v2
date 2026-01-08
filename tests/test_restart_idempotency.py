from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest


class _FakeSnap:
    def __init__(self, *, exists: bool, data: dict[str, Any] | None):
        self.exists = bool(exists)
        self._data = dict(data or {})

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


@dataclass
class _FakeDocRef:
    store: dict[str, dict[str, Any]]
    path: str

    def collection(self, name: str) -> "_FakeCollection":
        return _FakeCollection(store=self.store, path=f"{self.path}/{name}")

    def document(self, doc_id: str) -> "_FakeDocRef":
        return _FakeDocRef(store=self.store, path=f"{self.path}/{doc_id}")

    def create(self, data: dict[str, Any]) -> None:
        from google.api_core.exceptions import AlreadyExists

        if self.path in self.store:
            raise AlreadyExists("already exists")
        self.store[self.path] = dict(data)

    def set(self, data: dict[str, Any], merge: bool = False) -> None:  # noqa: FBT001,FBT002
        # Minimal behavior used by non-idempotent code paths.
        if merge and self.path in self.store:
            merged = dict(self.store[self.path])
            merged.update(dict(data))
            self.store[self.path] = merged
        else:
            self.store[self.path] = dict(data)

    def get(self) -> _FakeSnap:
        if self.path in self.store:
            return _FakeSnap(exists=True, data=self.store[self.path])
        return _FakeSnap(exists=False, data=None)


@dataclass
class _FakeCollection:
    store: dict[str, dict[str, Any]]
    path: str

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(store=self.store, path=f"{self.path}/{doc_id}")


class _FakeFirestore:
    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(store=self._store, path=name)


def test_insert_paper_order_idempotent_dedupes(monkeypatch):
    from backend.strategy_service.models import PaperOrderCreate
    from backend.strategy_service import db as paper_db

    fake = _FakeFirestore()
    monkeypatch.setattr(paper_db, "get_db", lambda: fake)
    monkeypatch.setattr(paper_db, "with_firestore_retry", lambda fn: fn())

    payload = PaperOrderCreate(
        uid="u1",
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="equity",
        side="buy",
        order_type="market",
        time_in_force="day",
        notional=1000.0,
        quantity=1.0,
        risk_allowed=True,
        risk_scope="account",
        risk_reason="ok",
        raw_order={"symbol": "SPY"},
        status="simulated",
    )

    key = "restart-test-key-1"
    r1 = paper_db.insert_paper_order_idempotent(tenant_id="t1", payload=payload, idempotency_key=key)
    r2 = paper_db.insert_paper_order_idempotent(tenant_id="t1", payload=payload, idempotency_key=key)

    assert r1.id == r2.id
    assert isinstance(r1.id, UUID)
    assert r1.created_at == r2.created_at

    # Only a single Firestore doc should exist for the derived UUID.
    docs = [p for p in fake._store.keys() if p.startswith("tenants/t1/paper_orders/")]
    assert len(docs) == 1


def test_shadow_trade_create_is_restart_idempotent(monkeypatch):
    from backend.tenancy.context import TenantContext
    from backend.strategy_service.routers import trades as trades_router

    fake = _FakeFirestore()
    monkeypatch.setattr(trades_router, "get_firestore_client", lambda: fake)
    monkeypatch.setattr(trades_router, "with_firestore_retry", lambda fn: fn())
    monkeypatch.setattr(trades_router, "get_current_price", lambda symbol: Decimal("100"))  # noqa: ARG005

    ctx = TenantContext(uid="u1", tenant_id="t1", claims={})

    trade_request = trades_router.TradeRequest(
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="equity",
        side="buy",
        order_type="market",
        time_in_force="day",
        notional=1000.0,
        quantity=0.0,
        idempotency_key="restart-test-key-2",
    )

    from backend.common.idempotency import stable_uuid_from_key

    shadow_id = str(stable_uuid_from_key(key=f"{ctx.tenant_id}:{ctx.uid}:shadow_trade:{trade_request.idempotency_key}"))

    t1 = trades_router.create_shadow_trade(trade_request, ctx, shadow_id=shadow_id)
    t2 = trades_router.create_shadow_trade(trade_request, ctx, shadow_id=shadow_id)

    assert t1["shadow_id"] == t2["shadow_id"] == shadow_id

    docs = [p for p in fake._store.keys() if p.startswith(f"users/{ctx.uid}/shadowTradeHistory/")]
    assert len(docs) == 1

