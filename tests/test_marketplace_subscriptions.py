from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.marketplace.models import MarketplaceStrategy, StrategySubscription


def test_marketplace_strategy_validates_id_and_tags():
    s = MarketplaceStrategy(strategy_id="strat_1", name="My Strat", tags=(" a ", "", "b"))
    assert s.strategy_id == "strat_1"
    assert s.tags == ("a", "b")

    with pytest.raises(ValueError):
        MarketplaceStrategy(strategy_id="bad/id", name="x")


def test_strategy_subscription_requires_uid_strategy_dates_and_active():
    start = datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    sub = StrategySubscription(
        tenant_id="t1",
        uid="uid_1",
        strategy_id="strat_1",
        start_at=start,
        end_at=end,
        active=True,
    )
    d = sub.to_firestore()
    assert d["uid"] == "uid_1"
    assert d["strategy_id"] == "strat_1"
    assert d["start_at"] == start
    assert d["end_at"] == end
    assert d["active"] is True

    with pytest.raises(ValueError):
        StrategySubscription(
            tenant_id="t1",
            uid="uid_1",
            strategy_id="strat_1",
            start_at=end,
            end_at=start,
        )

