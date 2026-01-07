import datetime as dt
from zoneinfo import ZoneInfo

from backend.marketdata.candles.timeframe import bar_range_utc, floor_time, parse_timeframe


def _utc(y, m, d, hh, mm, ss=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=dt.timezone.utc)


def test_1m_alignment_ny_wall_clock():
    tf = parse_timeframe("1m")
    # 2025-12-20 is EST (-05:00). 09:30:05 NY == 14:30:05 UTC.
    ts = _utc(2025, 12, 20, 14, 30, 5)
    s, e = bar_range_utc(ts, tf, tz="America/New_York")
    assert s == _utc(2025, 12, 20, 14, 30, 0)
    assert e == _utc(2025, 12, 20, 14, 31, 0)


def test_5m_alignment_ny_wall_clock_boundaries():
    tf = parse_timeframe("5m")
    # 09:34:59 NY == 14:34:59 UTC -> floors to 09:30 NY (14:30 UTC)
    s1 = floor_time(_utc(2025, 12, 20, 14, 34, 59), tf, tz="America/New_York")
    # 09:35:00 NY == 14:35:00 UTC -> starts new 5m bucket
    s2 = floor_time(_utc(2025, 12, 20, 14, 35, 0), tf, tz="America/New_York")
    assert s1 == _utc(2025, 12, 20, 14, 30, 0)
    assert s2 == _utc(2025, 12, 20, 14, 35, 0)


def test_15m_alignment_ny_wall_clock_boundaries():
    tf = parse_timeframe("15m")
    # 09:44:59 NY == 14:44:59 UTC -> floors to 09:30 NY
    s1 = floor_time(_utc(2025, 12, 20, 14, 44, 59), tf, tz="America/New_York")
    # 09:45:00 NY == 14:45:00 UTC -> new 15m bucket
    s2 = floor_time(_utc(2025, 12, 20, 14, 45, 0), tf, tz="America/New_York")
    assert s1 == _utc(2025, 12, 20, 14, 30, 0)
    assert s2 == _utc(2025, 12, 20, 14, 45, 0)


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

    s_before, e_before = bar_range_utc(before, tf, tz="America/New_York")
    s_after, e_after = bar_range_utc(after, tf, tz="America/New_York")

    assert s_after == ny_midnight_utc
    assert e_after == (ny_midnight + dt.timedelta(days=1)).astimezone(dt.timezone.utc)
    assert e_before == ny_midnight_utc
    assert s_before == (ny_midnight - dt.timedelta(days=1)).astimezone(dt.timezone.utc)

