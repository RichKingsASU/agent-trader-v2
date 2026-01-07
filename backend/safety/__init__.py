"""
Safety primitives (global kill-switch + health contracts).

This package is deliberately small and fail-closed:
- Missing / malformed config defaults to "halted"
- Unknown marketdata freshness defaults to "stale"
"""

from .safety_state import SafetyException, SafetyState, assert_safe_to_run, evaluate_safety_state, is_safe_to_run_strategies
from .config import load_kill_switch, load_stale_threshold_seconds

__all__ = [
    "SafetyException",
    "SafetyState",
    "assert_safe_to_run",
    "evaluate_safety_state",
    "is_safe_to_run_strategies",
    "load_kill_switch",
    "load_stale_threshold_seconds",
]

