"""
Kill-switch invariant tests.

These tests validate that the global kill-switch halts execution paths
without requiring any external services.
"""

from __future__ import annotations

import pytest

from backend.common.kill_switch import (
    ExecutionHaltedError,
    get_kill_switch_state,
    require_live_mode,
)


def test_kill_switch_env_halts_execution(monkeypatch):
    """
    Invariant: when kill-switch is enabled, execution must be halted.
    """
    monkeypatch.setenv("EXECUTION_HALTED", "1")

    with pytest.raises(ExecutionHaltedError):
        require_live_mode(operation="unit-test-op")


def test_kill_switch_file_halts_execution(tmp_path, monkeypatch):
    """
    Invariant: a truthy kill-switch file must halt execution.
    """
    p = tmp_path / "kill_switch.txt"
    p.write_text("true\n", encoding="utf-8")

    monkeypatch.delenv("EXECUTION_HALTED", raising=False)
    monkeypatch.setenv("EXECUTION_HALTED_FILE", str(p))

    enabled, source = get_kill_switch_state()
    assert enabled is True
    assert source == f"file:{p}"

