"""
Protocol-layer option intent models + adapters.

This package is intentionally broker-agnostic and pure/deterministic.
"""

from backend.options.option_intent import OptionOrderIntent, OptionType, Side
from backend.options.adapter import translate_equity_hedge_to_option_intent

__all__ = [
    "OptionOrderIntent",
    "OptionType",
    "Side",
    "translate_equity_hedge_to_option_intent",
]

