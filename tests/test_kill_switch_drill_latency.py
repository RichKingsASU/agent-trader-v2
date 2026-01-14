from __future__ import annotations

import asyncio

from scripts.kill_switch_drill import run_kill_switch_drill


def test_kill_switch_drill_pass_and_reports_latency():
    res = run_kill_switch_drill(warmup_s=0.05, loop_interval_s=0.005, timeout_s=2.0)
    assert res.passed is True
    assert res.proposals_after_trigger == 0
    assert res.orders_after_trigger == 0
    # Keep this generous for CI variance; intent is to detect regressions like missing checks.
    assert res.time_to_halt_s < 1.0


def test_strategy_engine_run_strategy_halts_immediately_on_kill_switch(monkeypatch):
    # Strategy evaluation should fail-closed and do no work when kill switch is enabled.
    monkeypatch.setenv("EXECUTION_HALTED", "1")

    from backend.strategy_engine import driver as drv

    def _boom(*args, **kwargs):
        raise AssertionError("strategy evaluation should not proceed while kill switch is enabled")

    monkeypatch.setattr(drv, "get_or_create_strategy_definition", _boom)
    monkeypatch.setattr(drv, "fetch_recent_bars", _boom)
    monkeypatch.setattr(drv, "fetch_recent_options_flow", _boom)

    asyncio.run(drv.run_strategy(execute=False))

