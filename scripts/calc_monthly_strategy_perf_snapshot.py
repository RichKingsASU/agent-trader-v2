#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from typing import Dict, Iterable, Optional

from backend.marketplace.strategy_performance_snapshots import (
    compute_monthly_strategy_performance_from_firestore,
    write_strategy_performance_snapshots,
)
from backend.persistence.firebase_client import get_firestore_client


def _parse_yyyy_mm(value: str) -> tuple[int, int]:
    try:
        year_s, month_s = value.split("-", 1)
        return int(year_s), int(month_s)
    except Exception as e:
        raise argparse.ArgumentTypeError("Expected YYYY-MM (e.g. 2025-12)") from e

def _parse_mark_prices(mark_price_args: Optional[Iterable[str]], marks_json: Optional[str]) -> Dict[str, float]:
    marks: Dict[str, float] = {}
    if marks_json:
        with open(marks_json, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            raise ValueError("--marks-json must be a JSON object mapping SYMBOL -> price")
        for k, v in obj.items():
            if isinstance(k, str) and isinstance(v, (int, float)):
                marks[k.strip().upper()] = float(v)

    for item in mark_price_args or []:
        if "=" not in item:
            raise ValueError("--mark-price must be in the form SYMBOL=PRICE (e.g. AAPL=125.5)")
        sym, px = item.split("=", 1)
        sym = sym.strip().upper()
        if not sym:
            raise ValueError("Empty symbol in --mark-price")
        marks[sym] = float(px)
    return marks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute monthly per-user strategy performance from Firestore ledger_trades (fill-level FIFO)."
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant id (tid)")
    parser.add_argument(
        "--uid",
        default=None,
        help="User id. If omitted, computes for all (uid, strategy_id) pairs in the tenant.",
    )
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Strategy id. If omitted, computes for all (uid, strategy_id) pairs in the tenant.",
    )
    parser.add_argument(
        "--month",
        required=True,
        type=_parse_yyyy_mm,
        help="Month to compute, format YYYY-MM (e.g. 2025-12)",
    )
    parser.add_argument(
        "--mark-price",
        action="append",
        default=None,
        help="Optional mark price for unrealized P&L, format SYMBOL=PRICE (repeatable).",
    )
    parser.add_argument(
        "--marks-json",
        default=None,
        help="Optional JSON file mapping SYMBOL -> mark price (merged with --mark-price).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the snapshot to tenants/{tid}/strategy_performance/{perf_id}. Default is dry-run.",
    )
    args = parser.parse_args()

    tenant_id = args.tenant_id
    uid: Optional[str] = args.uid
    strategy_id: Optional[str] = args.strategy_id
    year, month = args.month
    mark_prices = _parse_mark_prices(args.mark_price, args.marks_json)

    db = get_firestore_client()

    snapshots_by_perf_id = compute_monthly_strategy_performance_from_firestore(
        db=db,
        tenant_id=tenant_id,
        year=year,
        month=month,
        uid=uid,
        strategy_id=strategy_id,
        mark_prices=mark_prices,
    )

    for perf_id, snap in sorted(snapshots_by_perf_id.items(), key=lambda kv: kv[0]):
        snapshot_doc = snap.to_firestore_doc()
        printable = dict(snapshot_doc)
        printable["period_start"] = snap.period_start.isoformat()
        printable["period_end"] = snap.period_end.isoformat()
        printable["computed_at"] = "(server_timestamp)"
        print(f"perf_id={perf_id}")
        print(printable)

    if args.write:
        wrote = write_strategy_performance_snapshots(
            db=db,
            tenant_id=tenant_id,
            snapshots_by_perf_id=snapshots_by_perf_id,
            merge=True,
        )
        print(f"Wrote {wrote} snapshot docs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

