from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.dataplane import InMemoryNewsFeaturesProvider


def test_in_memory_news_features_provider_filters_and_is_read_only() -> None:
    fixed_now = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)

    provider = InMemoryNewsFeaturesProvider(
        now_fn=lambda: fixed_now,
        rows=[
            {"ts": datetime(2026, 1, 7, 11, 55, 0, tzinfo=timezone.utc), "symbol": "AAPL", "features": {"x": 1}},
            {"ts": datetime(2026, 1, 7, 11, 40, 0, tzinfo=timezone.utc), "symbol": "AAPL", "features": {"x": 2}},
            {"ts": datetime(2026, 1, 7, 11, 59, 0, tzinfo=timezone.utc), "symbol": "MSFT", "features": {"x": 3}},
        ],
    )

    rows = provider.get_recent_news_features("aapl", lookback_minutes=10)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["features"]["x"] == 1

    # Read-only: top-level mapping is immutable
    with pytest.raises(TypeError):
        rows[0]["symbol"] = "NOPE"  # type: ignore[misc]

