#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from google.cloud import firestore  # type: ignore

from backend.marketplace.fees import compute_monthly_performance_fee, parse_revenue_share_term, split_fee_amount
from backend.marketplace.performance import month_period_utc
from backend.marketplace.schema import TenantPaths, monthly_fee_id_for_subscription, monthly_perf_id
from backend.persistence.firebase_client import get_firestore_client
from backend.time.nyse_time import to_utc


def _parse_yyyy_mm(value: str) -> tuple[int, int]:
    try:
        year_s, month_s = value.split("-", 1)
        return int(year_s), int(month_s)
    except Exception as e:
        raise argparse.ArgumentTypeError("Expected YYYY-MM (e.g. 2025-12)") from e


def _to_firestore_ts(dt: datetime) -> datetime:
    return to_utc(dt)


def _resolve_uid(d: Mapping[str, Any]) -> Optional[str]:
    uid = d.get("uid") or d.get("user_id")
    if isinstance(uid, str) and uid.strip():
        return uid.strip()
    return None


def _resolve_strategy_id(d: Mapping[str, Any]) -> Optional[str]:
    sid = d.get("strategy_id") or d.get("marketplace_strategy_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute monthly performance fees from strategy_performance snapshots + revenue_share_terms."
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant id (tid)")
    parser.add_argument(
        "--month",
        required=True,
        type=_parse_yyyy_mm,
        help="Month to compute, format YYYY-MM (e.g. 2025-12)",
    )
    parser.add_argument("--uid", default=None, help="Optional subscriber uid filter.")
    parser.add_argument("--strategy-id", default=None, help="Optional strategy id filter.")
    parser.add_argument("--write", action="store_true", help="Write fee records. Default is dry-run.")
    args = parser.parse_args()

    tenant_id: str = args.tenant_id
    year, month = args.month
    uid_filter: Optional[str] = args.uid
    strategy_filter: Optional[str] = args.strategy_id

    period_start, period_end = month_period_utc(year=year, month=month)

    db = get_firestore_client()
    paths = TenantPaths(tenant_id=tenant_id)

    subs_ref = db.collection(paths.subscriptions)
    wrote = 0
    scanned = 0
    skipped = 0

    # Note: We intentionally stream subscriptions and filter in Python because the repo
    # has mixed field naming (uid vs user_id) and Firestore doesn't support OR queries.
    for snap in subs_ref.stream():
        scanned += 1
        sub_id = snap.id
        sub = snap.to_dict() or {}

        uid = _resolve_uid(sub)
        strategy_id = _resolve_strategy_id(sub)
        term_id = sub.get("revenue_share_term_id")

        if not isinstance(term_id, str) or not term_id.strip():
            skipped += 1
            continue
        term_id = term_id.strip()

        if uid is None or strategy_id is None:
            skipped += 1
            continue
        if uid_filter and uid != uid_filter:
            continue
        if strategy_filter and strategy_id != strategy_filter:
            continue

        term_path = f"{paths.revenue_share_terms}/{term_id}"
        term_snap = db.document(term_path).get()
        if not term_snap.exists:
            print(f"Skipping subscription {sub_id}: missing term doc {term_path}")
            skipped += 1
            continue
        term_dict = term_snap.to_dict() or {}
        term = parse_revenue_share_term(term_dict)
        if term is None:
            print(f"Skipping subscription {sub_id}: invalid term doc {term_path}")
            skipped += 1
            continue

        perf_id = monthly_perf_id(uid=uid, strategy_id=strategy_id, year=year, month=month)
        perf_path = f"{paths.strategy_performance}/{perf_id}"
        perf_snap = db.document(perf_path).get()
        if not perf_snap.exists:
            print(f"Skipping subscription {sub_id}: missing perf snapshot {perf_path}")
            skipped += 1
            continue
        perf = perf_snap.to_dict() or {}

        realized_pnl = float(perf.get("realized_pnl") or 0.0)
        fee_amount = compute_monthly_performance_fee(realized_pnl=realized_pnl, fee_rate=term.fee_rate)
        split = split_fee_amount(
            fee_amount=fee_amount,
            creator_pct=term.creator_pct,
            platform_pct=term.platform_pct,
            user_pct=term.user_pct,
        )

        fee_id = monthly_fee_id_for_subscription(subscription_id=sub_id, year=year, month=month)
        fee_doc: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "subscription_id": sub_id,
            "user_id": uid,
            "strategy_id": strategy_id,
            "revenue_share_term_id": term_id,
            "period_start": _to_firestore_ts(period_start),
            "period_end": _to_firestore_ts(period_end),
            "realized_pnl": realized_pnl,
            "fee_rate": float(term.fee_rate),
            "fee_amount": float(fee_amount),
            "creator_pct": float(term.creator_pct),
            "platform_pct": float(term.platform_pct),
            "user_pct": float(term.user_pct),
            **split,
            "perf_id": perf_id,
            "perf_ref": perf_path,
            "computed_at": firestore.SERVER_TIMESTAMP,
            "source": "strategy_performance_snapshot",
        }

        printable = dict(fee_doc)
        printable["period_start"] = period_start.isoformat()
        printable["period_end"] = period_end.isoformat()
        printable["computed_at"] = "(server_timestamp)"
        print(f"fee_id={fee_id}")
        print(printable)

        if args.write:
            fee_path = f"{paths.performance_fees}/{fee_id}"
            db.document(fee_path).set(fee_doc, merge=True)
            wrote += 1
            print(f"Wrote fee record to {fee_path}")

    print(f"Scanned {scanned} subscriptions. Skipped {skipped}.")
    if args.write:
        print(f"Wrote {wrote} fee records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

