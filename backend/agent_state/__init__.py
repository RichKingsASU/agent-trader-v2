"""
Institutional agent state machine (transport-agnostic).

This package is intentionally small and safe-by-default:
- No trading execution is enabled here.
- No external/cloud dependencies.
"""

from .state_machine import AgentEvent, AgentState, StateMachine  # noqa: F401

