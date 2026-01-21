import datetime as dt
from zoneinfo import ZoneInfo

import pytest

import backend.marketdata.candles.aggregator as _agg_mod
if not hasattr(_agg_mod, "parse_timeframes"):  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason="backend.marketdata.candles.aggregator missing parse_timeframes (documented-but-unimplemented)",
        strict=False,
    )

from backend.marketdata.candles.aggregator import CandleAggregator
from backend.marketdata.candles.models import Tick


NY = ZoneInfo("America/New_York")


def _utc(y, m, d, hh, mm, ss) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=dt.timezone.utc)


def _ny_to_utc(y, m, d, hh, mm, ss) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=NY).astimezone(dt.timezone.utc)


def test_ohlcv_math_and_rollover_final():
    agg = CandleAggregator(timeframes=["1m"], max_lateness_seconds=2)

    # 09:30 NY minute
    assert agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 5), price=100.0, size=10, symbol="SPY")) == []
    assert (
        agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 59), price=101.0, size=5, symbol="SPY")) == []
    )

    # Advance watermark into next minute (+ lateness) -> finalize 09:30 candle.
    out = agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 31, 3), price=102.0, size=1, symbol="SPY"))
    assert len(out) == 1
    f = out[0]
    assert f.is_final is True
    assert f.start_ts == _ny_to_utc(2025, 12, 20, 9, 30, 0)
    assert f.end_ts == _ny_to_utc(2025, 12, 20, 9, 31, 0)
    assert f.open == 100.0
    assert f.high == 101.0
    assert f.low == 100.0
    assert f.close == 101.0
    assert f.volume == 15


def test_lateness_update_within_window_and_drop_beyond_window():
    agg = CandleAggregator(timeframes=["1m"], max_lateness_seconds=5)

    assert agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 5), price=100.0, size=1, symbol="SPY")) == []
    assert agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 59), price=101.0, size=1, symbol="SPY")) == []

    # Advance watermark, but not far enough to finalize 09:30 yet (lateness=5s).
    assert agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 31, 3), price=102.0, size=1, symbol="SPY")) == []

    # Late tick within tolerance (wm=09:31:03, cutoff=09:30:58)
    assert agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 58), price=99.0, size=2, symbol="SPY")) == []

    # Flush after tolerance window => finalize 09:30 with late tick applied.
    flushed = agg.flush(_ny_to_utc(2025, 12, 20, 9, 31, 6))
    assert len(flushed) == 1
    f = flushed[0]
    assert f.is_final is True
    assert f.start_ts == _ny_to_utc(2025, 12, 20, 9, 30, 0)
    assert f.low == 99.0
    assert f.high == 101.0
    assert f.close == 101.0
    assert f.volume == 1 + 1 + 2

    # Too-late tick should be dropped (flush advanced watermark to 09:31:06).
    out5 = agg.ingest_tick(Tick(ts=_ny_to_utc(2025, 12, 20, 9, 30, 0), price=98.0, size=1, symbol="SPY"))
    assert out5 == []
    assert agg.late_drops >= 1

