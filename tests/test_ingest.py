import datetime as dt
from unittest.mock import MagicMock

import pytest


def test_importability():
    # backend.streams.alpaca_options_chain_ingest reads Alpaca creds at import time.
    import os
    os.environ.setdefault("APCA_API_KEY_ID", "mock_key")
    os.environ.setdefault("APCA_API_SECRET_KEY", "mock_secret")
    os.environ.setdefault("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    from backend.streams import alpaca_options_chain_ingest

    assert callable(alpaca_options_chain_ingest.main)


def test_get_env_required(monkeypatch):
    from backend.common.env import get_env

    monkeypatch.delenv("SOME_MISSING_ENV", raising=False)
    with pytest.raises(RuntimeError):
        get_env("SOME_MISSING_ENV", required=True)


def test_fetch_option_snapshots_paginates(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "mock_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "mock_secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    from backend.streams import alpaca_options_chain_ingest as mod

    r1 = MagicMock()
    r1.raise_for_status.return_value = None
    r1.json.return_value = {"snapshots": {"OPT1": {"x": 1}}, "next_page_token": "tok"}

    r2 = MagicMock()
    r2.raise_for_status.return_value = None
    r2.json.return_value = {"snapshots": {"OPT2": {"y": 2}}}

    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        return r1 if calls["n"] == 1 else r2

    monkeypatch.setattr(mod.requests, "get", fake_get)

    snaps, pages = mod.fetch_option_snapshots(underlying="SPY", feed="indicative", max_pages=3)
    assert pages == 2
    assert set(snaps.keys()) == {"OPT1", "OPT2"}


def test_upsert_snapshots_executes(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "mock_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "mock_secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    from backend.streams import alpaca_options_chain_ingest as mod

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    cursor_mgr = MagicMock()
    cursor_mgr.__enter__.return_value = mock_cur
    cursor_mgr.__exit__.return_value = False
    mock_conn.cursor.return_value = cursor_mgr

    monkeypatch.setattr(mod, "_connect_db", lambda *_args, **_kwargs: ("mock", mock_conn))

    snapshot_time = dt.datetime(2025, 12, 18, tzinfo=dt.timezone.utc)
    upserted = mod.upsert_snapshots(
        db_url="mock_db_url",
        snapshot_time=snapshot_time,
        underlying_symbol="SPY",
        snapshots={"OPT1": {"a": 1}, "OPT2": {"b": 2}},
    )

    assert upserted == 2
    assert mock_cur.executemany.call_count == 1
    sql = mock_cur.executemany.call_args.args[0]
    assert "public.alpaca_option_snapshots" in sql
    mock_conn.commit.assert_called_once()
