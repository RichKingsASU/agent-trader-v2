#!/usr/bin/env python3
"""
Explain the last observed option trade plan (read-only).

Sources (best-effort, in priority order):
- Local audit artifacts:
  - `audit_artifacts/proposals/<YYYY-MM-DD>/proposals.ndjson`
  - `audit_artifacts/execution_decisions/<YYYY-MM-DD>/decisions.ndjson`
- Optional captured stdout logs (if provided via --log)

This script is safe:
- reads only
- does not call broker APIs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_repo_on_path() -> None:
    rr = str(_repo_root())
    if rr not in sys.path:
        sys.path.insert(0, rr)


def _load_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plan JSON must be an object")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Explain the last observed option trade plan (read-only).")
    p.add_argument(
        "--audit-dir",
        default="audit_artifacts",
        help="Audit artifacts directory (default: audit_artifacts).",
    )
    p.add_argument(
        "--plan",
        default="",
        help="Optional path to a specific OptionTradePlan/OrderProposal JSON file.",
    )
    p.add_argument(
        "--log",
        action="append",
        default=[],
        help="Optional path to a captured stdout log file (repeatable).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of text.",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    _ensure_repo_on_path()

    from backend.observer.options_observer import explain_last_option_trade, explain_option_trade_plan

    audit_dir = Path(args.audit_dir)
    log_paths = [Path(x) for x in (args.log or []) if str(x).strip()]

    if args.plan and str(args.plan).strip():
        plan_path = Path(args.plan)
        rec = explain_option_trade_plan(
            plan=_load_json_file(plan_path),
            audit_dir=audit_dir,
            stdout_log_paths=log_paths,
        )
        # Preserve the explicit plan path in sources (no mutation/writes; just output).
        srcs = list(rec.sources)
        srcs.append(str(plan_path))
        seen: set[str] = set()
        uniq = tuple([s for s in srcs if not (s in seen or seen.add(s))])
        rec = rec.__class__(**{**rec.__dict__, "sources": uniq})
    else:
        rec = explain_last_option_trade(audit_dir=audit_dir, stdout_log_paths=log_paths)

    if args.json:
        sys.stdout.write(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        return 0

    sys.stdout.write(rec.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

