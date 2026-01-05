from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud.firestore import Client

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.tenancy.paths import tenant_collection

from .models import MarketplaceStrategy, StrategySubscription
from .schema import COLLECTION_MARKETPLACE_STRATEGIES, COLLECTION_SUBSCRIPTIONS


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def marketplace_strategies_collection(db: Optional[Client] = None):
    client = db or get_firestore_client()
    return client.collection(COLLECTION_MARKETPLACE_STRATEGIES)


def marketplace_strategy_ref(*, strategy_id: str, db: Optional[Client] = None):
    return marketplace_strategies_collection(db).document(strategy_id)


def tenant_subscriptions_collection(*, tenant_id: str, db: Optional[Client] = None):
    client = db or get_firestore_client()
    return tenant_collection(client, tenant_id=tenant_id, collection_name=COLLECTION_SUBSCRIPTIONS)


def tenant_subscription_ref(*, tenant_id: str, sub_id: str, db: Optional[Client] = None):
    return tenant_subscriptions_collection(tenant_id=tenant_id, db=db).document(sub_id)


def upsert_marketplace_strategy(*, listing: MarketplaceStrategy, db: Optional[Client] = None) -> None:
    """
    Create/update a marketplace listing.

    Writes:
      marketplace_strategies/{strategy_id}
    """
    doc = listing.to_firestore()
    doc.setdefault("created_at", _utc_now())
    doc["updated_at"] = _utc_now()
    ref = marketplace_strategy_ref(strategy_id=listing.strategy_id, db=db)
    with_firestore_retry(lambda: ref.set(doc, merge=True))


def upsert_subscription(*, sub_id: str, subscription: StrategySubscription, db: Optional[Client] = None) -> None:
    """
    Create/update a subscription under a tenant.

    Writes:
      tenants/{tid}/subscriptions/{sub_id}
    """
    if not sub_id or "/" in sub_id:
        raise ValueError("sub_id is required and must not contain '/'")

    doc: dict[str, Any] = subscription.to_firestore()
    doc.setdefault("created_at", _utc_now())
    doc["updated_at"] = _utc_now()

    ref = tenant_subscription_ref(tenant_id=subscription.tenant_id, sub_id=sub_id, db=db)
    with_firestore_retry(lambda: ref.set(doc, merge=True))

