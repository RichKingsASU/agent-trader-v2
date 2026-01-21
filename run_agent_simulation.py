#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _ensure_repo_on_path() -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _env_path(name: str) -> Path:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(f"missing required env var: {name}")
    p = Path(v).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"{name} not found: {p}")
    return p


def _write_events(path: Path, events: List[Dict[str, Any]]) -> None:
    from backend.strategy_runner.protocol import dumps_ndjson

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dumps_ndjson(events))


def main() -> int:
    _ensure_repo_on_path()

    from backend.scenarios.scenario_library import (
        generate_market_events_for_key,
        list_scenarios,
        normalize_scenario_key,
        scenario_key_aliases,
    )

    ap = argparse.ArgumentParser(description="Run an agent/strategy simulation with predefined market scenarios.")
    ap.add_argument("--list-scenarios", action="store_true", help="List available predefined scenarios and exit.")

    ap.add_argument(
        "--scenario",
        default=None,
        help="Predefined scenario key (aliases supported). If provided, --events is optional.",
    )
    ap.add_argument(
        "--events",
        default=None,
        help="Path to NDJSON market events. If omitted, --scenario must be provided to generate events.",
    )
    ap.add_argument(
        "--write-events",
        default=None,
        help="Optional path to write the generated scenario events NDJSON.",
    )

    ap.add_argument("--symbol", default="SPY", help="Symbol for generated scenarios (default: SPY).")
    ap.add_argument("--start-ts", default="2025-01-01T14:30:00Z", help="Scenario start timestamp (ISO8601, default: 2025-01-01T14:30:00Z).")
    ap.add_argument("--steps", type=int, default=390, help="Number of events to generate (default: 390 ~ 1 trading day at 1-min).")
    ap.add_argument("--interval-seconds", type=int, default=60, help="Seconds between events (default: 60).")
    ap.add_argument("--seed", type=int, default=7, help="Deterministic RNG seed (default: 7).")
    ap.add_argument("--start-price", type=float, default=100.0, help="Starting price for generated scenarios (default: 100.0).")

    ap.add_argument(
        "--strategy",
        default=str(_repo_root() / "backend" / "strategy_runner" / "examples" / "hello_strategy"),
        help="Path to uploaded strategy (file or directory).",
    )
    ap.add_argument("--strategy-id", default="sim", help="Strategy id label (default: sim).")
    ap.add_argument("--guest-cid", type=int, default=int(os.getenv("FC_GUEST_CID", "3")))
    ap.add_argument("--vsock-port", type=int, default=int(os.getenv("FC_VSOCK_PORT", "5005")))
    ap.add_argument(
        "--no-run",
        action="store_true",
        help="Only generate/write events; do not attempt to execute the strategy sandbox.",
    )

    args = ap.parse_args()

    if args.list_scenarios:
        aliases = scenario_key_aliases()
        by_key = {s.key: s for s in list_scenarios()}
        for key in sorted(by_key.keys()):
            s = by_key[key]
            # Print canonical key, name, description, and common aliases.
            a = sorted([k for k, v in aliases.items() if v == key and k != key])
            alias_txt = f" aliases={','.join(a)}" if a else ""
            sys.stdout.write(f"{key}\t{s.name}\t{s.description}{alias_txt}\n")
        return 0

    events_path: Optional[Path] = Path(args.events).expanduser().resolve() if args.events else None
    events: Optional[List[Dict[str, Any]]] = None

    if args.scenario:
        scenario_key = normalize_scenario_key(args.scenario)
        events = generate_market_events_for_key(
            scenario_key=scenario_key,
            symbol=args.symbol,
            start_ts=args.start_ts,
            steps=args.steps,
            interval_seconds=args.interval_seconds,
            seed=args.seed,
            start_price=args.start_price,
            source="sim",
        )
        if args.write_events:
            out_path = Path(args.write_events).expanduser().resolve()
            _write_events(out_path, events)
            events_path = out_path
        elif events_path is None:
            # If user didn't provide --events or --write-events, write to a temp file for traceability.
            tmp_dir = Path(tempfile.mkdtemp(prefix="agent_sim_"))
            out_path = tmp_dir / f"{scenario_key}.events.ndjson"
            _write_events(out_path, events)
            events_path = out_path

    if events is None:
        if events_path is None:
            raise SystemExit("Provide --scenario <key> or --events <path>.")
        # Load events from NDJSON
        from backend.strategy_runner.protocol import loads_ndjson

        events = loads_ndjson(events_path.read_bytes())

    if args.no_run:
        sys.stdout.write(json.dumps({"events_path": str(events_path) if events_path else None, "events_count": len(events)}, indent=2) + "\n")
        return 0

    # Execute inside Firecracker sandbox, matching backend.strategy_runner.harness.py behavior.
    from backend.strategy_runner.runner import FirecrackerAssets, StrategySandboxRunner

    assets = FirecrackerAssets(
        firecracker_bin=_env_path("FIRECRACKER_BIN"),
        kernel_image=_env_path("FC_KERNEL_IMAGE"),
        rootfs_image=_env_path("FC_ROOTFS_IMAGE"),
    )

    runner = StrategySandboxRunner(assets=assets, guest_cid=args.guest_cid, vsock_port=args.vsock_port)
    intents = runner.run(strategy_source=str(Path(args.strategy).resolve()), events=events, strategy_id=str(args.strategy_id))
    sys.stdout.write(json.dumps({"events_path": str(events_path) if events_path else None, "intents": intents}, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

