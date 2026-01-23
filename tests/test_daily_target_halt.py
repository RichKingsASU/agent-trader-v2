from __future__ import annotations

from backend.strategy_engine.daily_target_halt import (
    DAILY_TARGET_RETURN_PCT,
    DailyTargetHaltController,
    DailyTargetMetrics,
    compute_daily_return_pct,
)


def test_compute_daily_return_pct_basic():
    assert compute_daily_return_pct(current_equity_usd=104.0, starting_equity_usd=100.0) == 0.04
    assert compute_daily_return_pct(current_equity_usd=100.0, starting_equity_usd=100.0) == 0.0


def test_compute_daily_return_pct_zero_start_is_safe():
    assert compute_daily_return_pct(current_equity_usd=100.0, starting_equity_usd=0.0) == 0.0
    assert compute_daily_return_pct(current_equity_usd=100.0, starting_equity_usd=-10.0) == 0.0


def test_daily_target_halt_controller_halts_and_logs_once():
    logs: list[dict] = []

    def log_fn(**fields):
        logs.append(fields)

    metrics = DailyTargetMetrics(
        starting_equity_usd=100.0,
        current_equity_usd=104.0,
        daily_return_pct=0.04,
        updated_at_iso="2026-01-23T00:00:00+00:00",
    )
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return metrics

    t = {"now": 0.0}

    def now_mono():
        return t["now"]

    c = DailyTargetHaltController(
        strategy_name="s",
        tenant_id="t",
        uid="u",
        log_fn=log_fn,
        threshold=DAILY_TARGET_RETURN_PCT,
        metrics_provider=provider,
        check_interval_s=10.0,
        now_mono_fn=now_mono,
    )

    assert c.should_halt(symbol="SPY", iteration_id="it") is True
    assert c.halted is True
    assert calls["n"] == 1
    assert len(logs) == 1
    assert logs[0]["intent_type"] == "strategy.halted.daily_target"
    assert logs[0]["daily_return_pct"] == 0.04
    assert logs[0]["daily_target_pct"] == DAILY_TARGET_RETURN_PCT

    # Subsequent calls should not re-log or re-query.
    t["now"] = 1.0
    assert c.should_halt(symbol="SPY", iteration_id="it") is True
    assert calls["n"] == 1
    assert len(logs) == 1


def test_daily_target_halt_controller_caches_checks_when_not_halted():
    logs: list[dict] = []

    def log_fn(**fields):
        logs.append(fields)

    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        # Below threshold
        return DailyTargetMetrics(
            starting_equity_usd=100.0,
            current_equity_usd=103.0,
            daily_return_pct=0.03,
            updated_at_iso=None,
        )

    t = {"now": 0.0}

    def now_mono():
        return t["now"]

    c = DailyTargetHaltController(
        strategy_name="s",
        tenant_id="t",
        uid="u",
        log_fn=log_fn,
        metrics_provider=provider,
        check_interval_s=10.0,
        now_mono_fn=now_mono,
    )

    assert c.should_halt(symbol="SPY", iteration_id="it") is False
    assert calls["n"] == 1
    assert logs == []

    # Within interval: should not call provider again
    t["now"] = 5.0
    assert c.should_halt(symbol="SPY", iteration_id="it") is False
    assert calls["n"] == 1
    assert logs == []

