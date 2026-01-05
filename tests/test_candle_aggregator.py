import datetime as dt

from backend.marketdata.candles.aggregator import CandleAggregator


def _e(symbol: str, ts: dt.datetime, price: float, size: int) -> dict:
    return {"symbol": symbol, "timestamp": ts, "price": price, "size": size}


def _utc(y, m, d, hh, mm, ss) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=dt.timezone.utc)


def test_ohlcv_math_and_rollover_final():
    agg = CandleAggregator(timeframes=["1m"], lateness_seconds=5)

    out1 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 5), 100.0, 10))
    assert len(out1) == 1
    assert out1[0].is_final is False
    assert out1[0].open == 100.0
    assert out1[0].high == 100.0
    assert out1[0].low == 100.0
    assert out1[0].close == 100.0
    assert out1[0].volume == 10

    out2 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 59), 101.0, 5))
    assert len(out2) == 1
    assert out2[0].is_final is False
    assert out2[0].open == 100.0
    assert out2[0].high == 101.0
    assert out2[0].low == 100.0
    assert out2[0].close == 101.0
    assert out2[0].volume == 15

    # New bucket => rollover emits a final for 12:00 plus an update for 12:01.
    out3 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 1, 3), 102.0, 1))
    assert len(out3) == 2
    finals = [c for c in out3 if c.is_final]
    updates = [c for c in out3 if not c.is_final]
    assert len(finals) == 1
    assert len(updates) == 1

    f = finals[0]
    assert f.ts_start_utc == _utc(2025, 12, 20, 12, 0, 0)
    assert f.ts_end_utc == _utc(2025, 12, 20, 12, 1, 0)
    assert f.open == 100.0
    assert f.high == 101.0
    assert f.low == 100.0
    assert f.close == 101.0
    assert f.volume == 15


def test_lateness_update_within_window_and_drop_beyond_window():
    agg = CandleAggregator(timeframes=["1m"], lateness_seconds=5)

    agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 5), 100.0, 1))
    agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 59), 101.0, 1))

    # Advance watermark into next minute.
    out3 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 1, 3), 102.0, 1))
    assert any(c.is_final for c in out3)

    # Late trade within lateness window (wm=12:01:03, cutoff=12:00:58)
    out4 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 58), 99.0, 2))
    assert len(out4) == 1
    assert out4[0].is_final is False
    assert out4[0].ts_start_utc == _utc(2025, 12, 20, 12, 0, 0)
    assert out4[0].low == 99.0
    assert out4[0].high == 101.0
    assert out4[0].close == 101.0  # close stays last-by-timestamp
    assert out4[0].volume == 1 + 1 + 2

    # Now flush after lateness window has passed to re-emit final with updated values.
    flushed = agg.flush(_utc(2025, 12, 20, 12, 1, 6))
    finals = [c for c in flushed if c.is_final and c.ts_start_utc == _utc(2025, 12, 20, 12, 0, 0)]
    assert len(finals) == 1
    assert finals[0].low == 99.0
    assert finals[0].volume == 4

    # Too-late trade (older than watermark - lateness) should be dropped.
    out5 = agg.ingest(_e("SPY", _utc(2025, 12, 20, 12, 0, 0), 98.0, 1))
    assert out5 == []
    assert agg.late_events_dropped >= 1

