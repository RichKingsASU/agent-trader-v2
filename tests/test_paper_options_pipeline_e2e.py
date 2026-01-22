from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest


@dataclass
class _DummyRequest:
    headers: dict


class _LogCapture:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, _logger, event_type: str, **fields):  # noqa: ANN001
        self.events.append((str(event_type), dict(fields)))


def test_strategy_service_execute_trade_shadow_mode_emits_logs_and_creates_shadow_trade(monkeypatch):
    """
    End-to-end (hermetic) validation:
    - execution.attempt logged
    - risk check performed + logged
    - shadow trade created (no broker / no paper order insert)
    - execution.completed logged with mode=shadow
    """
    from backend.strategy_service.routers import trades as trades_router

    logcap = _LogCapture()
    monkeypatch.setattr(trades_router, "log_event", logcap.log_event)

    # Avoid firebase_admin initialization / ADC requirements (hermetic test).
    monkeypatch.setattr(trades_router, "get_firestore_client", lambda: object())

    # Ensure we stay in SHADOW mode and never touch broker/paper insert paths.
    monkeypatch.setattr(trades_router, "get_shadow_mode_flag", lambda: True)

    inserted = {"called": False}

    def _no_insert(*args, **kwargs):  # noqa: ANN001
        inserted["called"] = True
        raise AssertionError("paper order insert should not happen in shadow mode")

    monkeypatch.setattr(trades_router, "insert_paper_order_idempotent", _no_insert)
    monkeypatch.setattr(trades_router, "insert_paper_order", _no_insert)

    # Daily snapshot gate: bypass Firestore dependencies.
    monkeypatch.setattr(trades_router, "_require_daily_capital_snapshot", lambda **_kw: object())
    monkeypatch.setattr(trades_router, "_read_user_account_snapshot", lambda **_kw: {"equity": "10000"})

    # Risk check: return allowed=True without any network calls.
    @dataclass
    class _RiskResult:
        allowed: bool = True
        scope: str | None = "unit-test"
        reason: str | None = "ok"

    class _RiskClient:
        def __init__(self, *_a, **_kw):
            self.called = False

        def check_trade(self, *_a, **_kw):
            self.called = True
            return _RiskResult()

    risk_client = _RiskClient()
    monkeypatch.setattr(trades_router, "RiskAgentSyncClient", lambda *_a, **_kw: risk_client)

    # Shadow trade creation: return deterministic record (avoid Firestore write).
    shadow = {
        "shadow_id": "shadow_test_1",
        "created_at_iso": datetime.now(timezone.utc).isoformat(),
        "symbol": "SPY",
        "side": "buy",
        "quantity": "1",
        "entry_price": "1.23",
        "current_pnl": "0.00",
        "pnl_percent": "0.00",
    }
    monkeypatch.setattr(trades_router, "create_shadow_trade", lambda *_a, **_kw: shadow)

    # Tenant context: bypass auth.
    @dataclass
    class _Ctx:
        tenant_id: str
        uid: str

    monkeypatch.setattr(trades_router, "get_tenant_context", lambda _req: _Ctx(tenant_id="t1", uid="u1"))

    req = trades_router.TradeRequest(
        correlation_id="corr_1",
        signal_id="sig_1",
        allocation_id="alloc_1",
        execution_id="exec_1",
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="option",
        side="buy",
        order_type="market",
        time_in_force="day",
        notional=100.0,
        quantity=1.0,
        idempotency_key="idem_1",
    )
    out = trades_router.execute_trade(req, _DummyRequest(headers={}))

    assert out["mode"] == "shadow"
    assert out["id"] == "shadow_test_1"
    assert risk_client.called is True
    assert inserted["called"] is False

    ev_types = [e for (e, _f) in logcap.events]
    assert "execution.attempt" in ev_types
    assert "risk.trade_check.allowed" in ev_types
    assert "execution.completed" in ev_types


def test_strategy_service_execute_trade_paper_mode_creates_paper_order_and_emits_logs(monkeypatch):
    """
    End-to-end (hermetic) validation of the paper (non-shadow) branch:
    - risk check performed + logged
    - paper order insert performed (still no broker submission)
    - execution.completed logged with mode=paper
    """
    from backend.strategy_service.routers import trades as trades_router

    logcap = _LogCapture()
    monkeypatch.setattr(trades_router, "log_event", logcap.log_event)

    # Avoid firebase_admin initialization / ADC requirements (hermetic test).
    monkeypatch.setattr(trades_router, "get_firestore_client", lambda: object())

    monkeypatch.setattr(trades_router, "get_shadow_mode_flag", lambda: False)
    monkeypatch.setenv("EXECUTION_HALTED", "0")

    monkeypatch.setattr(trades_router, "_require_daily_capital_snapshot", lambda **_kw: object())
    monkeypatch.setattr(trades_router, "_read_user_account_snapshot", lambda **_kw: {"equity": "10000"})

    @dataclass
    class _RiskResult:
        allowed: bool = True
        scope: str | None = "unit-test"
        reason: str | None = "ok"

    class _RiskClient:
        def check_trade(self, *_a, **_kw):
            return _RiskResult()

    monkeypatch.setattr(trades_router, "RiskAgentSyncClient", lambda *_a, **_kw: _RiskClient())

    @dataclass
    class _Ctx:
        tenant_id: str
        uid: str

    monkeypatch.setattr(trades_router, "get_tenant_context", lambda _req: _Ctx(tenant_id="t1", uid="u1"))

    inserted: dict = {}

    @dataclass
    class _InsertResult:
        id: str

    def _insert_idempotent(*, tenant_id, payload, idempotency_key):  # noqa: ANN001
        inserted["tenant_id"] = tenant_id
        inserted["payload"] = payload
        inserted["idempotency_key"] = idempotency_key
        return _InsertResult(id="paper_order_1")

    monkeypatch.setattr(trades_router, "insert_paper_order_idempotent", _insert_idempotent)

    req = trades_router.TradeRequest(
        correlation_id="corr_2",
        signal_id="sig_2",
        allocation_id="alloc_2",
        execution_id="exec_2",
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="option",
        side="buy",
        order_type="market",
        time_in_force="day",
        notional=100.0,
        quantity=1.0,
        idempotency_key="idem_2",
    )
    out = trades_router.execute_trade(req, _DummyRequest(headers={}))

    assert getattr(out, "id", None) == "paper_order_1"
    assert inserted["tenant_id"] == "t1"
    assert inserted["idempotency_key"] == "idem_2"
    assert inserted["payload"].instrument_type == "option"

    evs = {e: f for (e, f) in logcap.events}
    assert "execution.attempt" in evs
    assert "risk.trade_check.allowed" in evs
    assert "execution.completed" in evs
    assert evs["execution.completed"].get("mode") == "paper"


def test_strategy_service_execute_trade_kill_switch_blocks_paper_mode(monkeypatch):
    """
    Kill switch must refuse non-shadow execution.
    """
    from backend.strategy_service.routers import trades as trades_router

    monkeypatch.setattr(trades_router, "get_shadow_mode_flag", lambda: False)
    monkeypatch.setenv("EXECUTION_HALTED", "1")

    # Avoid firebase_admin initialization / ADC requirements (hermetic test).
    monkeypatch.setattr(trades_router, "get_firestore_client", lambda: object())

    # Avoid Firestore dependencies (we should fail before any risk client call).
    monkeypatch.setattr(trades_router, "_require_daily_capital_snapshot", lambda **_kw: object())

    @dataclass
    class _Ctx:
        tenant_id: str
        uid: str

    monkeypatch.setattr(trades_router, "get_tenant_context", lambda _req: _Ctx(tenant_id="t1", uid="u1"))

    class _RiskClient:
        def check_trade(self, *_a, **_kw):
            raise AssertionError("risk check should not run when kill switch blocks non-shadow execution")

    monkeypatch.setattr(trades_router, "RiskAgentSyncClient", lambda *_a, **_kw: _RiskClient())

    req = trades_router.TradeRequest(
        correlation_id="corr_3",
        signal_id="sig_3",
        allocation_id="alloc_3",
        execution_id="exec_3",
        broker_account_id=uuid4(),
        strategy_id=uuid4(),
        symbol="SPY",
        instrument_type="option",
        side="buy",
        order_type="market",
        time_in_force="day",
        notional=100.0,
        quantity=1.0,
        idempotency_key="idem_3",
    )

    with pytest.raises(Exception) as e:
        trades_router.execute_trade(req, _DummyRequest(headers={}))
    # FastAPI HTTPException stringification varies; assert the code is present.
    assert "409" in str(e.value) or "kill_switch" in str(e.value).lower()


def test_cloudrun_consumer_trade_signals_handler_never_submits_without_double_confirm(monkeypatch):
    """
    The Pub/Sub consumer handler must not reach broker submission unless BOTH
    EXECUTION_ENABLED and EXECUTION_CONFIRM are truthy.
    """
    from cloudrun_consumer.handlers.trade_signals import handle_trade_signal
    import cloudrun_consumer.handlers.trade_signals as trade_signals_handler

    monkeypatch.delenv("EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("EXECUTION_CONFIRM", raising=False)

    def _submit_should_never_run(**_kw):
        raise AssertionError("broker submission should not be reached without explicit EXECUTION_* toggles")

    monkeypatch.setattr(trade_signals_handler, "submit_alpaca_option_order", _submit_should_never_run)

    class _Writer:
        def upsert_trade_signal(self, **_kw):
            return True, "applied"

    payload = {
        "symbol": "SPY",
        "strategy": "options_bot",
        "action": "buy",
        "option_symbol": "SPY260119C00500000",
        "qty": 1,
        "side": "buy",
        "order_type": "market",
        "time_in_force": "day",
    }
    out = handle_trade_signal(
        payload=payload,
        env="local",
        default_region="local",
        source_topic="test",
        message_id="m1",
        pubsub_published_at=datetime.now(timezone.utc),
        firestore_writer=_Writer(),
        replay=None,
    )
    assert out["applied"] is True
    assert "alpacaOrderId" not in out


def test_cloudrun_consumer_refuses_live_alpaca_base_url():
    """
    Hard stop condition: live Alpaca endpoints must be refused.
    """
    from cloudrun_consumer.handlers.trade_signals import _assert_paper_alpaca_base_url

    with pytest.raises(RuntimeError, match="REFUSED: non-paper Alpaca base URL"):
        _assert_paper_alpaca_base_url("https://api.alpaca.markets")

