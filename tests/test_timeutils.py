from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.common.timeutils import (
    UTC,
    nyse_isoformat,
    parse_alpaca_timestamp,
    to_nyse_time,
    to_utc_time,
)


def _assert_tz_key(dt: datetime, expected_key: str) -> None:
    assert dt.tzinfo is not None
    tz_key = getattr(dt.tzinfo, "key", None)
    assert tz_key == expected_key


def test_iso_z_winter_to_ny() -> None:
    # 14:30Z is 09:30 NY in winter (EST, -05:00)
    x = "2025-01-02T14:30:00Z"
    ny = to_nyse_time(x)
    assert ny.year == 2025 and ny.month == 1 and ny.day == 2
    assert ny.hour == 9 and ny.minute == 30 and ny.second == 0
    _assert_tz_key(ny, "America/New_York")
    assert ny.utcoffset().total_seconds() == -5 * 3600


def test_iso_z_summer_to_ny_dst() -> None:
    # 13:30Z is 09:30 NY in summer (EDT, -04:00)
    x = "2025-06-03T13:30:00Z"
    ny = to_nyse_time(x)
    assert ny.year == 2025 and ny.month == 6 and ny.day == 3
    assert ny.hour == 9 and ny.minute == 30 and ny.second == 0
    _assert_tz_key(ny, "America/New_York")
    assert ny.utcoffset().total_seconds() == -4 * 3600


def test_naive_datetime_assumed_utc() -> None:
    x = datetime(2025, 1, 2, 14, 30)  # naive => assume UTC
    ny = to_nyse_time(x)
    assert (ny.year, ny.month, ny.day, ny.hour, ny.minute) == (2025, 1, 2, 9, 30)
    _assert_tz_key(ny, "America/New_York")
    assert ny.utcoffset().total_seconds() == -5 * 3600


def test_epoch_seconds_and_ms_same_moment() -> None:
    base_utc = datetime(2025, 1, 2, 14, 30, 0, tzinfo=timezone.utc)
    epoch_s = int(base_utc.timestamp())
    epoch_ms = epoch_s * 1000

    dt_s = parse_alpaca_timestamp(epoch_s)
    dt_ms = parse_alpaca_timestamp(epoch_ms)

    _assert_tz_key(dt_s, "UTC")
    _assert_tz_key(dt_ms, "UTC")
    assert dt_s == dt_ms
    assert dt_s == base_utc.astimezone(UTC)


def test_offset_string_roundtrips() -> None:
    x = "2025-01-02T09:30:00-05:00"
    ny = to_nyse_time(x)
    assert ny.hour == 9 and ny.minute == 30
    _assert_tz_key(ny, "America/New_York")
    assert ny.utcoffset().total_seconds() == -5 * 3600

    # Roundtrip invariant: NY -> UTC equals canonical parsed UTC moment
    assert to_utc_time(to_nyse_time(x)) == parse_alpaca_timestamp(x)


def test_nyse_isoformat_includes_offset_and_millis() -> None:
    x = "2025-01-02T14:30:00Z"
    s = nyse_isoformat(x, timespec="milliseconds")
    assert s.startswith("2025-01-02T09:30:00.000")
    assert s.endswith("-05:00")


def test_pandas_timestamp_supported_if_installed() -> None:
    pd = pytest.importorskip("pandas")
    ts = pd.Timestamp("2025-01-02T14:30:00Z")
    out = parse_alpaca_timestamp(ts)
    _assert_tz_key(out, "UTC")
    assert out == parse_alpaca_timestamp("2025-01-02T14:30:00Z")

