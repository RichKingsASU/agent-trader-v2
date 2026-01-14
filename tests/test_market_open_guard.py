from __future__ import annotations

from datetime import datetime

import pytest

import backend.execution.engine as exec_engine
from backend.execution.engine import OrderIntent, RiskConfig, RiskManager
from backend.time.nyse_time import NYSE_TZ, UTC


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = int(trades_today)

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)


class _PositionsStub:
    def __init__(self, qty: float = 0.0):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


def _risk_allow():
    return RiskManager(
        config=RiskConfig(max_position_qty=100000, max_daily_trades=999, fail_open=True),
        ledger=_LedgerStub(trades_today=0),
        positions=_PositionsStub(qty=0),
    )


def _intent():
    return OrderIntent(strategy_id="s1", broker_account_id="acct1", symbol="SPY", side="buy", qty=1)


def _set_now(monkeypatch, *, ny_dt: datetime) -> None:
    assert ny_dt.tzinfo is not None
    now_utc = ny_dt.astimezone(UTC)
    monkeypatch.setattr(exec_engine, "_utc_now", lambda: now_utc)


def test_market_open_guard_blocks_by_default_first_15_minutes(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_MARKET_OPEN_COOLDOWN_MINUTES", raising=False)
    monkeypatch.delenv("EXEC_MARKET_OPEN_GUARD_ENABLED", raising=False)

    # 5 minutes after open (09:35 NY)
    _set_now(monkeypatch, ny_dt=datetime(2026, 1, 2, 9, 35, 0, tzinfo=NYSE_TZ))

    r = _risk_allow().validate(intent=_intent())
    assert r.allowed is False
    assert r.reason == "market_open_cooldown"


def test_market_open_guard_allows_after_cooldown(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_MARKET_OPEN_COOLDOWN_MINUTES", raising=False)
    monkeypatch.delenv("EXEC_MARKET_OPEN_GUARD_ENABLED", raising=False)

    # 20 minutes after open (09:50 NY)
    _set_now(monkeypatch, ny_dt=datetime(2026, 1, 2, 9, 50, 0, tzinfo=NYSE_TZ))

    r = _risk_allow().validate(intent=_intent())
    assert r.allowed is True


def test_market_open_guard_minutes_override_disables_when_zero(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXEC_MARKET_OPEN_COOLDOWN_MINUTES", "0")
    monkeypatch.delenv("EXEC_MARKET_OPEN_GUARD_ENABLED", raising=False)

    # Still at 09:35 NY, but cooldown=0 => allowed
    _set_now(monkeypatch, ny_dt=datetime(2026, 1, 2, 9, 35, 0, tzinfo=NYSE_TZ))

    r = _risk_allow().validate(intent=_intent())
    assert r.allowed is True


def test_market_open_guard_enabled_toggle_off(monkeypatch):
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXEC_MARKET_OPEN_GUARD_ENABLED", "false")
    monkeypatch.delenv("EXEC_MARKET_OPEN_COOLDOWN_MINUTES", raising=False)

    _set_now(monkeypatch, ny_dt=datetime(2026, 1, 2, 9, 35, 0, tzinfo=NYSE_TZ))

    r = _risk_allow().validate(intent=_intent())
    assert r.allowed is True

