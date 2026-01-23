from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4


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
        class AlreadyExists(Exception):
            pass

        if self.path in self.store:
            raise AlreadyExists("already exists")
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


class _LogCapture:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def log_event(self, _logger, event_type: str, **fields):  # noqa: ANN001
        self.events.append((str(event_type), dict(fields)))


def _make_intent(*, tenant_id: str = "t1", intent_id: UUID | None = None, quantity: str | None = "1", meta: Mapping[str, Any] | None = None):
    from backend.contracts.v2.trading import OptionOrderIntent

    iid = intent_id or uuid4()
    return OptionOrderIntent(
        schema="agenttrader.v2.option_order_intent",
        schema_version="2.0.0",
        tenant_id=tenant_id,
        created_at=datetime.now(timezone.utc),
        correlation_id="corr_1",
        intent_id=iid,
        account_id="acct_1",
        strategy_id="s1",
        symbol="SPY",
        asset_class="option",
        side="buy",
        order_type="market",
        time_in_force="day",
        quantity=quantity,
        contract_symbol="SPY260119C00500000",
        expiration=date(2026, 1, 19),
        strike="500",
        right="call",
        meta=dict(meta or {}),
    )


def _make_resolved():
    from backend.marketdata.options.models import QuoteMetrics, SelectedOptionContract

    q = QuoteMetrics(
        bid=1.0,
        ask=1.2,
        bid_size=10,
        ask_size=12,
        volume=100,
        open_interest=1000,
        snapshot_time="now",
    )
    return SelectedOptionContract(
        contract_symbol="SPY260119C00500000",
        underlying_symbol="SPY",
        right="call",
        strike=500.0,
        expiration_date=date(2026, 1, 19),
        dte=1,
        underlying_price=500.0,
        quote=q,
        raw_snapshot={"latestQuote": {"bp": 1.0, "ap": 1.2}},
    )


def test_shadow_option_executor_duplicate_intent_replay_dedupes_and_logs(monkeypatch):
    from backend.options.shadow_executor import ShadowOptionExecutor
    from backend.storage.shadow_option_trades import ShadowOptionTradeStore

    fake = _FakeFirestore()
    store = ShadowOptionTradeStore(db=fake)

    logcap = _LogCapture()
    import backend.options.shadow_executor as shadow_mod

    monkeypatch.setattr(shadow_mod, "log_event", logcap.log_event)

    ex = ShadowOptionExecutor(store=store)
    intent = _make_intent()
    resolved = _make_resolved()

    r1 = ex.execute(intent=intent, resolved_contract=resolved, reason="unit_test")
    r2 = ex.execute(intent=intent, resolved_contract=resolved, reason="unit_test")

    assert r1["status"] == "simulated"
    assert r1["applied"] is True
    assert r2["status"] == "skipped"
    assert r2["applied"] is False
    assert r2["reason"] == "duplicate_intent_replay"
    assert r1["doc_id"] == r2["doc_id"]

    # Only one Firestore doc in shadowTradeHistory.
    docs = [p for p in fake._store.keys() if p.startswith("shadowTradeHistory/")]
    assert len(docs) == 1

    ev_types = [e for (e, _f) in logcap.events]
    assert "option.execution.attempt" in ev_types
    assert "option.execution.simulated" in ev_types
    assert "option.execution.skipped" in ev_types


def test_shadow_option_executor_restart_safety_new_executor_instance_is_idempotent(monkeypatch):
    from backend.options.shadow_executor import ShadowOptionExecutor
    from backend.storage.shadow_option_trades import ShadowOptionTradeStore

    fake = _FakeFirestore()
    store = ShadowOptionTradeStore(db=fake)

    logcap = _LogCapture()
    import backend.options.shadow_executor as shadow_mod

    monkeypatch.setattr(shadow_mod, "log_event", logcap.log_event)

    intent = _make_intent()
    resolved = _make_resolved()

    ex1 = ShadowOptionExecutor(store=store)
    ex2 = ShadowOptionExecutor(store=store)

    r1 = ex1.execute(intent=intent, resolved_contract=resolved, reason="unit_test_restart")
    r2 = ex2.execute(intent=intent, resolved_contract=resolved, reason="unit_test_restart")

    assert r1["status"] == "simulated"
    assert r2["status"] == "skipped"
    assert r2["reason"] == "duplicate_intent_replay"

    docs = [p for p in fake._store.keys() if p.startswith("shadowTradeHistory/")]
    assert len(docs) == 1


def test_shadow_option_executor_hold_path_skips_without_write_and_logs(monkeypatch):
    from backend.options.shadow_executor import ShadowOptionExecutor
    from backend.storage.shadow_option_trades import ShadowOptionTradeStore

    fake = _FakeFirestore()
    store = ShadowOptionTradeStore(db=fake)

    logcap = _LogCapture()
    import backend.options.shadow_executor as shadow_mod

    monkeypatch.setattr(shadow_mod, "log_event", logcap.log_event)

    ex = ShadowOptionExecutor(store=store)
    intent = _make_intent(meta={"action": "hold"})
    resolved = _make_resolved()

    r = ex.execute(intent=intent, resolved_contract=resolved, reason="unit_test_hold")

    assert r["status"] == "skipped"
    assert r["applied"] is False
    assert str(r["reason"]).startswith("hold:")

    docs = [p for p in fake._store.keys() if p.startswith("shadowTradeHistory/")]
    assert len(docs) == 0

    evs = {e: f for (e, f) in logcap.events}
    assert "option.execution.attempt" in evs
    assert "option.execution.skipped" in evs

