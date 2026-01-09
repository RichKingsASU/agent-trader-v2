from __future__ import annotations

import os


class ExecutionConfirmTokenError(RuntimeError):
    """
    Raised when a live-execution confirmation token is missing/incorrect.

    Design intent:
    - Present in code now, but only enforced if/when a future live trading mode is enabled.
    - Provides a second, explicit, operator-supplied confirmation beyond config flags.
    """


def require_confirm_token_for_live_execution(*, provided_token: str | None) -> None:
    """
    Fail-closed unless the provided token matches the expected runtime token.

    Contract:
    - Expected token is read from EXECUTION_CONFIRM_TOKEN.
    - If EXECUTION_CONFIRM_TOKEN is missing/empty => refuse (fail closed).
    - If provided token is missing/incorrect => refuse.
    """
    expected = str(os.getenv("EXECUTION_CONFIRM_TOKEN") or "").strip()
    if not expected:
        raise ExecutionConfirmTokenError(
            "Refusing live execution: EXECUTION_CONFIRM_TOKEN is missing/empty "
            "(confirmation token gate is fail-closed)."
        )
    provided = str(provided_token or "").strip()
    if not provided:
        raise ExecutionConfirmTokenError(
            "Refusing live execution: missing confirmation token "
            "(provide X-Exec-Confirm-Token)."
        )
    if provided != expected:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token mismatch.")

