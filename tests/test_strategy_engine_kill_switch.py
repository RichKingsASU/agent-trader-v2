from __future__ import annotations

import asyncio
import builtins


def test_strategy_engine_halts_on_kill_switch(monkeypatch) -> None:
    """
    Invariant: when the global kill switch is enabled, the strategy engine must
    not evaluate cycles and must not touch external dependencies (DB/network).
    """
    monkeypatch.setenv("EXECUTION_HALTED", "1")

    # Import after env is set (mirrors real runtime conditions).
    from backend.strategy_engine import driver as d  # noqa: WPS433

    # If the kill-switch check is correctly placed, the strategy runtime should
    # return before importing DB-backed modules (e.g., asyncpg).
    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name in {"backend.strategy_engine.models", "backend.strategy_engine.models"} or (
            str(name).endswith(".strategy_engine.models")
        ):
            raise AssertionError("unexpected import of strategy_engine.models while kill switch enabled")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    asyncio.run(d.run_strategy(execute=False))

