from __future__ import annotations

from .loader import load_strategy_contract
from .schema import StrategyContract


def validate_strategy_contract(strategy_id: str) -> StrategyContract:
    """
    Schema-first enforcement entrypoint.

    - Requires a contract file to exist for the strategy_id.
    - Validates enums + cross-field constraints (fail-closed).

    Raises:
    - ValueError for invalid contract contents
    - FileNotFoundError when contract is missing
    """
    return load_strategy_contract(strategy_id)

