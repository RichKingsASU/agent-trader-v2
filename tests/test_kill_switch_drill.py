from __future__ import annotations

import os

from scripts.kill_switch_drill import run_drill


def test_kill_switch_drill_local_file_backed(monkeypatch):
    # Keep env isolated from developer shells / CI.
    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH", raising=False)
    monkeypatch.delenv("EXECUTION_HALTED_FILE", raising=False)
    monkeypatch.delenv("EXEC_KILL_SWITCH_FILE", raising=False)

    monkeypatch.setenv("AGENT_MODE", "LIVE")

    r = run_drill(strategy_poll_interval_s=0.005)

    assert r.kill_switch_source is not None
    assert r.broker_orders_before == 0
    assert r.broker_orders_after == 0  # no new orders after activation

    # "Instant" is environment-dependent; enforce a tight but realistic bound.
    # (This is local file IO + a short polling loop.)
    assert 0 <= r.time_to_strategy_halt_ms < 500
    assert 0 <= r.time_to_execution_reject_ms < 500

