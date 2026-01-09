from datetime import date, timedelta

import pytest

from backend.risk.daily_capital_snapshot import DailyCapitalSnapshot, DailyCapitalSnapshotError


def test_snapshot_roundtrip_and_fingerprint_verification():
    d = date(2026, 1, 6)  # weekday, non-holiday
    snap = DailyCapitalSnapshot.for_today_from_account_snapshot(
        tenant_id="t1",
        uid="u1",
        trading_date_ny=d,
        account_snapshot={"equity": "10000", "cash": "2500", "buying_power": "8000", "updated_at_iso": "2026-01-06T14:30:00+00:00"},
        now_utc=None,
        source="test",
    )
    loaded = DailyCapitalSnapshot.from_dict(snap.to_dict())
    assert loaded.fingerprint == snap.fingerprint
    assert loaded.starting_equity_usd == 10000.0
    assert loaded.trading_date_ny == d


def test_snapshot_tamper_detected_by_fingerprint():
    d = date(2026, 1, 6)
    snap = DailyCapitalSnapshot.for_today_from_account_snapshot(
        tenant_id="t1",
        uid="u1",
        trading_date_ny=d,
        account_snapshot={"equity": 10000, "cash": 2500, "buying_power": 8000},
        source="test",
    )
    payload = snap.to_dict()
    payload["starting_equity_usd"] = 9999.0  # mutation
    with pytest.raises(DailyCapitalSnapshotError, match="fingerprint mismatch"):
        DailyCapitalSnapshot.from_dict(payload)


def test_snapshot_date_mismatch_fails_hard():
    d = date(2026, 1, 6)
    snap = DailyCapitalSnapshot.for_today_from_account_snapshot(
        tenant_id="t1",
        uid="u1",
        trading_date_ny=d,
        account_snapshot={"equity": 10000, "cash": 2500, "buying_power": 8000},
        source="test",
    )
    with pytest.raises(DailyCapitalSnapshotError, match="Trading day mismatch"):
        snap.assert_date_match(trading_date_ny=d + timedelta(days=1))


def test_snapshot_trade_window_enforced():
    d = date(2026, 1, 6)
    snap = DailyCapitalSnapshot.for_today_from_account_snapshot(
        tenant_id="t1",
        uid="u1",
        trading_date_ny=d,
        account_snapshot={"equity": 10000, "cash": 2500, "buying_power": 8000},
        source="test",
    )

    # before open
    with pytest.raises(DailyCapitalSnapshotError, match="not yet valid"):
        snap.assert_trade_window(now_utc=snap.valid_from_utc - timedelta(seconds=1))

    # at/after close
    with pytest.raises(DailyCapitalSnapshotError, match="expired"):
        snap.assert_trade_window(now_utc=snap.expires_at_utc + timedelta(seconds=1))

    # during session
    snap.assert_trade_window(now_utc=snap.valid_from_utc + timedelta(minutes=1))

