from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.common.freshness import (
    check_freshness,
    coerce_utc,
    latest_timestamp,
    stale_after_for_bar_interval,
)


class _Item:
    def __init__(self, ts: datetime) -> None:
        self.ts = ts


def test_coerce_utc_assumes_naive_is_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)  # naive
    out, assumed = coerce_utc(naive)
    assert assumed is True
    assert out.tzinfo is timezone.utc
    assert out.isoformat().endswith("+00:00")


def test_latest_timestamp_empty_returns_none() -> None:
    assert latest_timestamp([]) is None


def test_latest_timestamp_picks_max() -> None:
    t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    assert latest_timestamp([_Item(t1), _Item(t2), _Item(t1)]) == t2


def test_stale_after_for_bar_interval_is_2x_by_default() -> None:
    assert stale_after_for_bar_interval(bar_interval=timedelta(seconds=60)).total_seconds() == 120


def test_check_freshness_missing_timestamp_is_stale() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = check_freshness(latest_ts=None, stale_after=timedelta(seconds=30), now=now, source="test")
    assert res.ok is False
    assert res.reason_code == "MISSING_TIMESTAMP"
    assert res.latest_ts_utc is None
    assert res.age is None


def test_check_freshness_fresh_when_age_under_threshold() -> None:
    now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    latest = datetime(2026, 1, 1, 12, 0, 10, tzinfo=timezone.utc)
    res = check_freshness(latest_ts=latest, stale_after=timedelta(seconds=30), now=now, source="test")
    assert res.ok is True
    assert res.reason_code == "FRESH"
    assert res.age is not None and res.age.total_seconds() == 20


def test_check_freshness_boundary_equal_threshold_is_fresh() -> None:
    now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
    latest = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = check_freshness(latest_ts=latest, stale_after=timedelta(seconds=30), now=now, source="test")
    assert res.ok is True
    assert res.reason_code == "FRESH"


def test_check_freshness_stale_when_age_over_threshold() -> None:
    now = datetime(2026, 1, 1, 12, 0, 31, tzinfo=timezone.utc)
    latest = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    res = check_freshness(latest_ts=latest, stale_after=timedelta(seconds=30), now=now, source="test")
    assert res.ok is False
    assert res.reason_code == "STALE_DATA"
    assert res.age is not None and res.age.total_seconds() == 31

