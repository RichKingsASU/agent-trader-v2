from __future__ import annotations

"""
Canonical NATS subject builders.

See: docs/MESSAGING.md
"""

from typing import Final

_FORBIDDEN_TOKEN_CHARS: Final[set[str]] = {".", "*", ">"}


def _token(value: str, *, name: str) -> str:
    """
    Validate and normalize a single NATS subject token.

    - Must be non-empty after trimming
    - Must not contain '.', '*', '>' (wildcards are for subscriptions only)
    """

    if value is None:
        raise ValueError(f"{name} is required")
    v = str(value).strip()
    if not v:
        raise ValueError(f"{name} is required")

    if any(ch in v for ch in _FORBIDDEN_TOKEN_CHARS):
        raise ValueError(
            f"{name} token contains forbidden characters (.,*,>): {value!r}"
        )
    return v


def market_subject(tenant_id: str, symbol: str) -> str:
    return f"market.{_token(tenant_id, name='tenant_id')}.{_token(symbol, name='symbol')}"


def market_wildcard_subject(tenant_id: str) -> str:
    """
    Subscribe to all market subjects for a tenant.
    """

    return f"market.{_token(tenant_id, name='tenant_id')}.>"


def signals_subject(tenant_id: str, strategy_id: str, symbol: str) -> str:
    return (
        f"signals.{_token(tenant_id, name='tenant_id')}"
        f".{_token(strategy_id, name='strategy_id')}"
        f".{_token(symbol, name='symbol')}"
    )


def signals_v2_subject(tenant_id: str, strategy_id: str, symbol: str) -> str:
    """
    Canonical subject for v2 TradingSignal messages.

    Intentionally separate from legacy `signals.*` subjects to avoid consumers
    accidentally decoding the wrong schema version.
    """

    return (
        f"signals_v2.{_token(tenant_id, name='tenant_id')}"
        f".{_token(strategy_id, name='strategy_id')}"
        f".{_token(symbol, name='symbol')}"
    )


def orders_subject(tenant_id: str, account_id: str) -> str:
    return f"orders.{_token(tenant_id, name='tenant_id')}.{_token(account_id, name='account_id')}"


def fills_subject(tenant_id: str, account_id: str) -> str:
    return f"fills.{_token(tenant_id, name='tenant_id')}.{_token(account_id, name='account_id')}"


def ops_subject(tenant_id: str, service: str) -> str:
    return f"ops.{_token(tenant_id, name='tenant_id')}.{_token(service, name='service')}"

