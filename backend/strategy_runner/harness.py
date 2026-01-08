from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from .protocol import loads_ndjson
from .runner import FirecrackerAssets, StrategySandboxRunner


def _required_path(name: str) -> Path:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"missing required env var: {name}")
    p = Path(v).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"{name} not found: {p}")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a user strategy inside Firecracker (local harness).")
    ap.add_argument(
        "--strategy",
        default=str(Path(__file__).parent / "examples" / "hello_strategy"),
        help="Path to uploaded strategy (file or directory).",
    )
    ap.add_argument(
        "--events",
        default=str(Path(__file__).parent / "examples" / "hello_strategy" / "events.ndjson"),
        help="Path to NDJSON market events.",
    )
    ap.add_argument("--guest-cid", type=int, default=int(os.getenv("FC_GUEST_CID", "3")))
    ap.add_argument("--vsock-port", type=int, default=int(os.getenv("FC_VSOCK_PORT", "5005")))
    args = ap.parse_args()

    assets = FirecrackerAssets(
        firecracker_bin=_required_path("FIRECRACKER_BIN"),
        kernel_image=_required_path("FC_KERNEL_IMAGE"),
        rootfs_image=_required_path("FC_ROOTFS_IMAGE"),
    )

    strategy_path = Path(args.strategy).resolve()
    events_path = Path(args.events).resolve()
    events: List[Dict[str, Any]] = loads_ndjson(events_path.read_bytes())

    runner = StrategySandboxRunner(assets=assets, guest_cid=args.guest_cid, vsock_port=args.vsock_port)
    intents = runner.run(strategy_source=strategy_path, events=events, strategy_id="hello")
    sys.stdout.write(json.dumps(intents, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

