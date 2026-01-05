from __future__ import annotations

"""
Firestore collection naming + ID conventions for the Strategy Marketplace.

Collections requested by the user story:
- marketplace_strategies/{strategy_id} (global/public listing)
- tenants/{tid}/subscriptions/{sub_id}
- tenants/{tid}/revenue_share_terms/{term_id}
- tenants/{tid}/strategy_performance/{perf_id}

This file intentionally avoids Firestore reads/writes; it provides path helpers and deterministic IDs
used by scripts/services.
"""

from dataclasses import dataclass


COLLECTION_MARKETPLACE_STRATEGIES = "marketplace_strategies"

COLLECTION_TENANTS = "tenants"
COLLECTION_SUBSCRIPTIONS = "subscriptions"
COLLECTION_REVENUE_SHARE_TERMS = "revenue_share_terms"
COLLECTION_STRATEGY_PERFORMANCE = "strategy_performance"
COLLECTION_PERFORMANCE_FEES = "performance_fees"

# Not part of the requested "model" list, but required for perf snapshot computation.
COLLECTION_LEDGER_TRADES = "ledger_trades"


@dataclass(frozen=True)
class TenantPaths:
    tenant_id: str

    @property
    def tenant_doc(self) -> str:
        return f"{COLLECTION_TENANTS}/{self.tenant_id}"

    @property
    def subscriptions(self) -> str:
        return f"{self.tenant_doc}/{COLLECTION_SUBSCRIPTIONS}"

    @property
    def revenue_share_terms(self) -> str:
        return f"{self.tenant_doc}/{COLLECTION_REVENUE_SHARE_TERMS}"

    @property
    def strategy_performance(self) -> str:
        return f"{self.tenant_doc}/{COLLECTION_STRATEGY_PERFORMANCE}"

    @property
    def performance_fees(self) -> str:
        return f"{self.tenant_doc}/{COLLECTION_PERFORMANCE_FEES}"

    @property
    def ledger_trades(self) -> str:
        return f"{self.tenant_doc}/{COLLECTION_LEDGER_TRADES}"


def marketplace_strategy_doc(strategy_id: str) -> str:
    return f"{COLLECTION_MARKETPLACE_STRATEGIES}/{strategy_id}"


def monthly_perf_id(
    *,
    uid: str | None = None,
    user_id: str | None = None,
    strategy_id: str,
    year: int,
    month: int,
) -> str:
    """
    Deterministic performance snapshot document id.

    Example: "uid_123__strat_abc__2025-12"
    """
    resolved_uid = uid if uid is not None else user_id
    if not resolved_uid:
        raise ValueError("uid (or user_id) is required")
    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")
    return f"{resolved_uid}__{strategy_id}__{year:04d}-{month:02d}"


def monthly_fee_id_for_subscription(*, subscription_id: str, year: int, month: int) -> str:
    """
    Deterministic monthly fee record document id (idempotent per subscription per month).

    Example: "sub_01H...__2025-12"
    """
    sid = (subscription_id or "").strip()
    if not sid:
        raise ValueError("subscription_id is required")
    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")
    return f"{sid}__{year:04d}-{month:02d}"

