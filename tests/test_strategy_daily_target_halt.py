from datetime import date


def test_read_daily_return_pct_normalizes_percent(monkeypatch):
    from backend.strategy_engine.daily_target_halt import read_daily_return_pct

    monkeypatch.setenv("DAILY_RETURN_PCT", "4")
    assert read_daily_return_pct() == 0.04


def test_daily_target_halt_latch_halts_and_resets_by_day():
    from backend.strategy_engine.daily_target_halt import DailyTargetHaltLatch

    latch = DailyTargetHaltLatch()
    d1 = date(2026, 1, 1)
    d2 = date(2026, 1, 2)

    assert latch.is_halted(today=d1, daily_return_pct=0.039) is False
    assert latch.is_halted(today=d1, daily_return_pct=0.04) is True
    # Once halted, stays halted for the day regardless of later value.
    assert latch.is_halted(today=d1, daily_return_pct=0.0) is True

    # New day resets.
    assert latch.is_halted(today=d2, daily_return_pct=0.0) is False

