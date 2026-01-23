"""
Options utilities (deterministic, in-memory).

This package is intentionally:
- network-free (no broker / market data calls)
- execution-free (no order placement)
- deterministic and explainable (stable tie-breakers, explicit reasons)
"""

from .selector import (  # noqa: F401
    ContractSelectionError,
    MarketSnapshot,
    OptionOrderIntentLike,
    OptionSelectorConfig,
    OptionType,
    ResolvedOptionContract,
    SyntheticOptionQuote,
    resolve_option_contract,
)

