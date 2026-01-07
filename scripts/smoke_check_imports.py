#!/usr/bin/env python3
"""
Import smoke test to prevent missing-dependency deploys.

This intentionally imports the Python entrypoints for always-on services so that
missing runtime dependencies show up as a fast, deterministic failure in CI.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportTarget:
    module: str
    note: str


DEFAULT_TARGETS: tuple[ImportTarget, ...] = (
    ImportTarget("backend.app", "marketdata-mcp-server entrypoint"),
    ImportTarget("backend.strategy_engine.service", "strategy-engine service app"),
    ImportTarget("backend.services.execution_service.app", "execution-engine service app"),
    ImportTarget("backend.streams_bridge.main", "stream bridge service"),
    ImportTarget("backend.risk_service.app", "risk service app"),
    ImportTarget("backend.mission_control.main", "mission-control service app"),
    ImportTarget("backend.execution_agent.main", "execution agent"),
    ImportTarget("backend.ingestion.market_data_ingest", "market ingest job"),
    ImportTarget("backend.ingestion.congressional_disclosures", "congressional ingest job"),
    ImportTarget("backend.strategies.registry.loader", "strategy loader (yaml parsing)"),
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import smoke test for critical modules")
    p.add_argument(
        "--module",
        action="append",
        default=[],
        help="Additional module to import (repeatable).",
    )
    p.add_argument(
        "--no-defaults",
        action="store_true",
        help="Do not import the default module set; only use --module.",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    # Ensure repo root is on sys.path when invoked from CI.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    targets: list[ImportTarget] = []
    if not args.no_defaults:
        targets.extend(DEFAULT_TARGETS)
    targets.extend(ImportTarget(m, "user-specified") for m in args.module)

    if not targets:
        print("ERROR: no modules specified to import", file=sys.stderr)
        return 2

    failures: list[tuple[ImportTarget, BaseException]] = []
    for t in targets:
        try:
            importlib.import_module(t.module)
            print(f"OK   import {t.module}  ({t.note})")
        except BaseException as e:  # noqa: BLE001 - intentional for import-time failures
            failures.append((t, e))
            print(f"FAIL import {t.module}  ({t.note})", file=sys.stderr)
            traceback.print_exc()

    if failures:
        print("", file=sys.stderr)
        print("Import smoke check failed.", file=sys.stderr)
        print("Modules that failed to import:", file=sys.stderr)
        for t, e in failures:
            print(f"- {t.module}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
