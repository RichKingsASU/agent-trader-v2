import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from backend.marketdata.candles.timeframes import bucket_range_utc, parse_timeframe


def _utc(y, m, d, hh, mm, ss=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=dt.timezone.utc)


def test_1m_alignment_utc_floor():
    tf = parse_timeframe("1m")
    s1, e1 = bucket_range_utc(_utc(2025, 12, 20, 12, 0, 5), tf)
    s2, e2 = bucket_range_utc(_utc(2025, 12, 20, 12, 0, 59), tf)
    s3, e3 = bucket_range_utc(_utc(2025, 12, 20, 12, 1, 0), tf)

    assert s1 == _utc(2025, 12, 20, 12, 0, 0)
    assert e1 == _utc(2025, 12, 20, 12, 1, 0)
    assert s2 == s1 and e2 == e1
    assert s3 == _utc(2025, 12, 20, 12, 1, 0)
    assert e3 == _utc(2025, 12, 20, 12, 2, 0)


def test_5m_alignment_utc_floor():
    tf = parse_timeframe("5m")
    s1, _ = bucket_range_utc(_utc(2025, 12, 20, 12, 4, 59), tf)
    s2, _ = bucket_range_utc(_utc(2025, 12, 20, 12, 5, 0), tf)

    assert s1 == _utc(2025, 12, 20, 12, 0, 0)
    assert s2 == _utc(2025, 12, 20, 12, 5, 0)


def test_1d_alignment_ny_midnight_boundary_dst_aware():
    """
    Daily buckets align to America/New_York midnight (not UTC midnight).
    Pick a summer date to ensure DST offset is exercised.
    """
    tf = parse_timeframe("1d")
    ny = ZoneInfo("America/New_York")

    ny_midnight = dt.datetime(2025, 7, 1, 0, 0, 0, tzinfo=ny)
    ny_midnight_utc = ny_midnight.astimezone(dt.timezone.utc)

    before = ny_midnight_utc - dt.timedelta(minutes=1)
    after = ny_midnight_utc + dt.timedelta(minutes=1)

    s_before, e_before = bucket_range_utc(before, tf, tz_market="America/New_York")
    s_after, e_after = bucket_range_utc(after, tf, tz_market="America/New_York")

    assert s_after == ny_midnight_utc
    assert e_after == (ny_midnight + dt.timedelta(days=1)).astimezone(dt.timezone.utc)
    assert e_before == ny_midnight_utc
    assert s_before == (ny_midnight - dt.timedelta(days=1)).astimezone(dt.timezone.utc)


def test_1w_alignment_monday_ny_00_00():
    tf = parse_timeframe("1w")
    ny = ZoneInfo("America/New_York")

    # A Monday local midnight boundary
    monday = dt.datetime(2025, 12, 1, 0, 0, 0, tzinfo=ny)
    assert monday.weekday() == 0  # Monday

    just_before = monday - dt.timedelta(minutes=1)  # Sunday 23:59 local
    just_after = monday + dt.timedelta(minutes=1)   # Monday 00:01 local

    s_before, e_before = bucket_range_utc(just_before.astimezone(dt.timezone.utc), tf, tz_market="America/New_York")
    s_after, e_after = bucket_range_utc(just_after.astimezone(dt.timezone.utc), tf, tz_market="America/New_York")

    assert s_after == monday.astimezone(dt.timezone.utc)
    assert e_after == (monday + dt.timedelta(days=7)).astimezone(dt.timezone.utc)
    assert e_before == monday.astimezone(dt.timezone.utc)
    assert s_before == (monday - dt.timedelta(days=7)).astimezone(dt.timezone.utc)

