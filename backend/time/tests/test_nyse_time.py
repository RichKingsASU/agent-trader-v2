from __future__ import annotations

from datetime import datetime

import pytest

from backend.time import nyse_time


def test_parse_ts_iso_z_and_naive_iso() -> None:
    dt_z = nyse_time.parse_ts("2025-01-02T14:30:00Z")
    assert dt_z.tzinfo is not None
    assert dt_z.tzinfo == nyse_time.UTC
    assert dt_z.isoformat() == "2025-01-02T14:30:00+00:00"

    # Naive ISO is treated as UTC by canonical rule.
    dt_naive = nyse_time.parse_ts("2025-01-02T14:30:00")
    assert dt_naive.tzinfo == nyse_time.UTC
    assert dt_naive == dt_z


def test_parse_ts_epoch_seconds_vs_milliseconds() -> None:
    sec = 1_700_000_000
    ms = 1_700_000_000_000

    dt_sec = nyse_time.parse_ts(sec)
    dt_ms = nyse_time.parse_ts(ms)

    assert dt_sec.tzinfo == nyse_time.UTC
    assert dt_ms.tzinfo == nyse_time.UTC
    assert dt_sec == dt_ms


def test_to_nyse_dst_offsets_two_known_dates() -> None:
    # Winter: EST (-05:00)
    dt_utc_winter = datetime(2025, 1, 15, 14, 30, 0, tzinfo=nyse_time.UTC)
    dt_ny_winter = nyse_time.to_nyse(dt_utc_winter)
    assert dt_ny_winter.hour == 9 and dt_ny_winter.minute == 30
    assert dt_ny_winter.utcoffset().total_seconds() == -5 * 3600

    # Summer: EDT (-04:00)
    dt_utc_summer = datetime(2025, 7, 1, 13, 30, 0, tzinfo=nyse_time.UTC)
    dt_ny_summer = nyse_time.to_nyse(dt_utc_summer)
    assert dt_ny_summer.hour == 9 and dt_ny_summer.minute == 30
    assert dt_ny_summer.utcoffset().total_seconds() == -4 * 3600


def test_market_open_close_known_trading_day_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force fallback (weekday-only) behavior for determinism in minimal envs.
    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "false")
    nyse_time._CAL = None  # type: ignore[attr-defined]

    d = datetime(2025, 1, 2, 12, 0, 0, tzinfo=nyse_time.NYSE_TZ).date()  # Thu
    assert nyse_time.is_trading_day(d) is True

    o = nyse_time.market_open_dt(d)
    c = nyse_time.market_close_dt(d)
    assert o.tzinfo == nyse_time.NYSE_TZ
    assert c.tzinfo == nyse_time.NYSE_TZ
    assert (o.hour, o.minute) == (9, 30)
    assert (c.hour, c.minute) == (16, 0)


def test_exchange_calendar_holiday_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    if not nyse_time.exchange_calendar_available():
        pytest.skip("exchange_calendars not installed in this environment")

    monkeypatch.setenv("USE_EXCHANGE_CALENDAR", "true")
    nyse_time._CAL = None  # type: ignore[attr-defined]

    # New Year's Day is a market holiday (calendar-aware check).
    assert nyse_time.is_trading_day(datetime(2025, 1, 1).date()) is False


def test_floor_and_ceil_to_timeframe_in_ny() -> None:
    # 2025-01-02 14:33:45Z == 09:33:45 NY (EST)
    dt = datetime(2025, 1, 2, 14, 33, 45, tzinfo=nyse_time.UTC)

    flo = nyse_time.floor_to_timeframe(dt, "5m", tz="America/New_York")
    cei = nyse_time.ceil_to_timeframe(dt, "5m", tz="America/New_York")

    assert flo.tzinfo is not None
    assert cei.tzinfo is not None
    assert flo.isoformat() == "2025-01-02T09:30:00-05:00"
    assert cei.isoformat() == "2025-01-02T09:35:00-05:00"

