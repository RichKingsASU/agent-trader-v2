from __future__ import annotations

from datetime import datetime

import pytest

from backend.execution import engine as exec_engine
from backend.execution.engine import OrderIntent, RiskConfig, RiskManager
from backend.time import nyse_time


class _LedgerStub:
    def count_trades_today(self, *, broker_account_id: str, trading_date: str, tenant_id: str | None = None) -> int:  # noqa: ARG002
        return 0


class _PositionsStub:
    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return 0.0


def _risk_mgr() -> RiskManager:
    return RiskManager(
        config=RiskConfig(max_position_qty=10_000, max_daily_trades=10_000, fail_open=True),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )


def test_market_open_block_window_default_15(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force fallback hours for determinism (weekday-only, 09:30–16:00 NY time)
    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "false")
    nyse_time._CAL = None  # type: ignore[attr-defined]

    # Enable guard (override tests/conftest.py)
    monkeypatch.setenv("MARKET_OPEN_BLOCK_MINUTES", "15")

    # 2025-01-02 14:35Z == 09:35 NY (EST): within first 15 minutes after open.
    monkeypatch.setattr(
        exec_engine,
        "_utc_now",
        lambda: datetime(2025, 1, 2, 14, 35, 0, tzinfo=nyse_time.UTC),
    )

    risk = _risk_mgr().validate(
        intent=OrderIntent(strategy_id="s", broker_account_id="a", symbol="SPY", side="buy", qty=1)
    )
    assert risk.allowed is False
    assert risk.reason == "market_open_block_window"


def test_market_open_allows_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "false")
    nyse_time._CAL = None  # type: ignore[attr-defined]
    monkeypatch.setenv("MARKET_OPEN_BLOCK_MINUTES", "15")

    # 09:46 NY: outside the 09:30–09:45 block window.
    monkeypatch.setattr(
        exec_engine,
        "_utc_now",
        lambda: datetime(2025, 1, 2, 14, 46, 0, tzinfo=nyse_time.UTC),
    )

    risk = _risk_mgr().validate(
        intent=OrderIntent(strategy_id="s", broker_account_id="a", symbol="SPY", side="buy", qty=1)
    )
    assert risk.allowed is True
    assert risk.reason == "ok"


def test_market_open_guard_disabled_with_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "false")
    nyse_time._CAL = None  # type: ignore[attr-defined]
    monkeypatch.setenv("MARKET_OPEN_BLOCK_MINUTES", "0")

    # 09:35 NY would normally be blocked, but guard is disabled.
    monkeypatch.setattr(
        exec_engine,
        "_utc_now",
        lambda: datetime(2025, 1, 2, 14, 35, 0, tzinfo=nyse_time.UTC),
    )

    risk = _risk_mgr().validate(
        intent=OrderIntent(strategy_id="s", broker_account_id="a", symbol="SPY", side="buy", qty=1)
    )
    assert risk.allowed is True


def test_market_open_env_invalid_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "false")
    nyse_time._CAL = None  # type: ignore[attr-defined]
    monkeypatch.setenv("MARKET_OPEN_BLOCK_MINUTES", "not_an_int")

    # Within the default 15-minute window => should still block.
    monkeypatch.setattr(
        exec_engine,
        "_utc_now",
        lambda: datetime(2025, 1, 2, 14, 35, 0, tzinfo=nyse_time.UTC),
    )

    risk = _risk_mgr().validate(
        intent=OrderIntent(strategy_id="s", broker_account_id="a", symbol="SPY", side="buy", qty=1)
    )
    assert risk.allowed is False
    assert risk.reason == "market_open_block_window"

