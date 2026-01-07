from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.dataplane.file_store import FileCandleStore, FileProposalStore, FileTickStore


def _utc(y: int, m: int, d: int, hh: int, mm: int, ss: int) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setenv("DATA_PLANE_ROOT", str(root))
    return root


def test_tick_store_writes_correct_partition_and_appends_ndjson(data_root: Path) -> None:
    store = FileTickStore()

    sym = "BTC/USD"
    store.write_ticks(
        sym,
        [
            {"symbol": sym, "timestamp": "2026-01-07T00:00:01Z", "price": 100.0, "size": 1},
        ],
    )
    store.write_ticks(
        sym,
        [
            {"symbol": sym, "timestamp": "2026-01-07T00:00:02Z", "price": 101.0, "size": 2},
        ],
    )

    p = data_root / "ticks" / "2026" / "01" / "07" / "BTC_USD.ndjson"
    assert p.exists()

    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rec1 = json.loads(lines[0])
    rec2 = json.loads(lines[1])
    assert rec1["symbol"] == sym
    assert rec2["symbol"] == sym
    assert rec1["timestamp"].endswith("+00:00") or rec1["timestamp"].endswith("Z")


def test_tick_store_query_date_range_filters(data_root: Path) -> None:
    store = FileTickStore()
    sym = "SPY"

    store.write_ticks(
        sym,
        [
            {"symbol": sym, "timestamp": "2026-01-07T23:59:59Z", "price": 100.0, "size": 1},
            {"symbol": sym, "timestamp": "2026-01-08T00:00:01Z", "price": 101.0, "size": 1},
        ],
    )

    out = store.query_ticks(sym, _utc(2026, 1, 7, 0, 0, 0), _utc(2026, 1, 7, 23, 59, 59))
    assert len(out) == 1
    assert out[0]["price"] == 100.0


def test_candle_store_paths_and_query(data_root: Path) -> None:
    store = FileCandleStore()
    sym = "BRK.B"
    tf = "1m"

    store.write_candles(
        sym,
        tf,
        [
            {
                "symbol": sym,
                "timeframe": tf,
                "ts_start_utc": "2026-01-07T12:00:00Z",
                "ts_end_utc": "2026-01-07T12:01:00Z",
                "open": 1.0,
                "high": 2.0,
                "low": 1.0,
                "close": 2.0,
                "volume": 10,
                "is_final": True,
            }
        ],
    )

    p = data_root / "candles" / tf / "2026" / "01" / "07" / "BRK.B.ndjson"
    assert p.exists()

    out = store.query_candles(sym, tf, _utc(2026, 1, 7, 0, 0, 0), _utc(2026, 1, 7, 23, 59, 59))
    assert len(out) == 1
    assert out[0]["symbol"] == sym
    assert out[0]["timeframe"] == tf


def test_proposal_store_partition_path(data_root: Path) -> None:
    store = FileProposalStore()
    store.write_proposals(
        [
            {
                "proposal_id": "p1",
                "created_at_utc": "2026-01-07T00:00:00Z",
                "strategy_name": "test",
                "symbol": "SPY",
                "status": "PROPOSED",
            }
        ]
    )

    p = data_root / "proposals" / "2026" / "01" / "07" / "proposals.ndjson"
    assert p.exists()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["proposal_id"] == "p1"

