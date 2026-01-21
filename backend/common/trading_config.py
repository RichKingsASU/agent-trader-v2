"""
Shared trading configuration values.

These are deliberately lightweight and environment-driven so they can be used by:
- strategy runner examples
- backend strategies
- cloud functions

No broker calls or execution plumbing should live here.
"""

from __future__ import annotations

import os


def get_options_contract_multiplier() -> int:
    """
    Standard US listed equity option contract multiplier.

    Delta from most data sources is quoted "per 1 share" of underlying for 1 contract.
    To convert per-contract delta into share-equivalent delta, multiply by:
        contracts * OPTIONS_CONTRACT_MULTIPLIER

    Env:
        OPTIONS_CONTRACT_MULTIPLIER (default: 100)
    """
    raw = (os.getenv("OPTIONS_CONTRACT_MULTIPLIER") or "").strip()
    if not raw:
        return 100
    try:
        v = int(raw)
        return v if v > 0 else 100
    except Exception:
        return 100


# Convenience constant for modules that want a single import.
OPTIONS_CONTRACT_MULTIPLIER: int = get_options_contract_multiplier()

