"""
Kill-switch drill harness (local, deterministic).

Goal:
- Trigger kill switch via file-backed mechanism (EXECUTION_HALTED_FILE)
- Confirm:
  - "strategies halt" => proposal loop stops
  - "no new orders placed" => execution loop stops before "placing"
  - measure stop latency

This is intentionally self-contained: no broker/network/DB dependencies.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from backend.common.kill_switch import ExecutionHaltedError, get_kill_switch_state, require_live_mode


@dataclass(frozen=True)
class DrillResult:
    passed: bool
    time_to_halt_s: float
    trigger_source: str
    strategy_halt_s: float
    execution_halt_s: float
    proposals_before_trigger: int
    orders_before_trigger: int
    proposals_after_trigger: int
    orders_after_trigger: int


def _write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def run_kill_switch_drill(
    *,
    warmup_s: float = 0.15,
    loop_interval_s: float = 0.01,
    timeout_s: float = 5.0,
) -> DrillResult:
    """
    Returns a DrillResult with measured latencies.

    Time-to-halt is defined as max(strategy_halt_s, execution_halt_s) from trigger time.
    """
    warmup_s = max(0.0, float(warmup_s))
    loop_interval_s = max(0.0, float(loop_interval_s))
    timeout_s = max(0.1, float(timeout_s))

    # Use file-backed kill switch to simulate the Kubernetes ConfigMap volume mount behavior.
    d = Path(tempfile.mkdtemp(prefix="kill_switch_drill_"))
    ks_file = d / "EXECUTION_HALTED"
    _write_text_atomic(ks_file, "0\n")

    # Ensure env-var kill switch isn't interfering; prefer file-backed semantics for the drill.
    os.environ.pop("EXECUTION_HALTED", None)
    os.environ["EXECUTION_HALTED_FILE"] = str(ks_file)

    # For the execution loop: authorize trading via agent mode so kill switch is the deciding factor.
    os.environ["AGENT_MODE"] = "LIVE"

    lock = threading.Lock()
    proposals = 0
    orders = 0
    trigger_t: float | None = None
    strategy_halt_t: float | None = None
    execution_halt_t: float | None = None
    last_proposal_t: float | None = None
    last_order_t: float | None = None

    stop_event = threading.Event()

    def strategy_loop() -> None:
        nonlocal proposals, strategy_halt_t, last_proposal_t
        while not stop_event.is_set():
            enabled, _src = get_kill_switch_state()
            now = time.monotonic()
            if enabled:
                with lock:
                    if strategy_halt_t is None:
                        strategy_halt_t = now
                return
            with lock:
                proposals += 1
                last_proposal_t = now
            time.sleep(loop_interval_s)

    def execution_loop() -> None:
        nonlocal orders, execution_halt_t, last_order_t
        while not stop_event.is_set():
            now = time.monotonic()
            try:
                # This models the last-line safety boundary right before any broker-side side effect.
                require_live_mode(operation="kill-switch-drill:place_order")
            except ExecutionHaltedError:
                with lock:
                    if execution_halt_t is None:
                        execution_halt_t = now
                return
            with lock:
                orders += 1
                last_order_t = now
            time.sleep(loop_interval_s)

    t_strategy = threading.Thread(target=strategy_loop, name="kill-switch-drill-strategy", daemon=True)
    t_exec = threading.Thread(target=execution_loop, name="kill-switch-drill-execution", daemon=True)
    t_strategy.start()
    t_exec.start()

    # Warm up.
    time.sleep(warmup_s)

    # Trigger kill switch.
    trigger_t = time.monotonic()
    _write_text_atomic(ks_file, "1\n")
    trigger_source = f"file:{ks_file}"

    # Wait for both loops to halt (or timeout).
    deadline = trigger_t + timeout_s
    while time.monotonic() < deadline:
        with lock:
            if strategy_halt_t is not None and execution_halt_t is not None:
                break
        time.sleep(0.001)

    stop_event.set()
    t_strategy.join(timeout=1.0)
    t_exec.join(timeout=1.0)

    with lock:
        # Snapshot counts.
        proposals_total = proposals
        orders_total = orders
        lp = last_proposal_t
        lo = last_order_t
        sh = strategy_halt_t
        eh = execution_halt_t

    # Compute before/after trigger counts by approximating "after trigger" as any events whose last timestamp is after trigger.
    # Since the loops exit on first observation, "after trigger" should be 0 in steady state; we keep this strict.
    proposals_after = 1 if (lp is not None and trigger_t is not None and lp > trigger_t) else 0
    orders_after = 1 if (lo is not None and trigger_t is not None and lo > trigger_t) else 0

    # Latencies (fail if any halt time missing).
    if trigger_t is None or sh is None or eh is None:
        passed = False
        strategy_halt_s = float("inf") if sh is None else max(0.0, sh - trigger_t)
        execution_halt_s = float("inf") if eh is None else max(0.0, eh - trigger_t)
    else:
        strategy_halt_s = max(0.0, sh - trigger_t)
        execution_halt_s = max(0.0, eh - trigger_t)
        passed = (proposals_after == 0) and (orders_after == 0)

    time_to_halt_s = max(strategy_halt_s, execution_halt_s)

    return DrillResult(
        passed=passed,
        time_to_halt_s=time_to_halt_s,
        trigger_source=trigger_source,
        strategy_halt_s=strategy_halt_s,
        execution_halt_s=execution_halt_s,
        proposals_before_trigger=max(0, proposals_total - proposals_after),
        orders_before_trigger=max(0, orders_total - orders_after),
        proposals_after_trigger=proposals_after,
        orders_after_trigger=orders_after,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Local kill-switch drill harness")
    ap.add_argument("--warmup-s", type=float, default=0.15)
    ap.add_argument("--loop-interval-s", type=float, default=0.01)
    ap.add_argument("--timeout-s", type=float, default=5.0)
    args = ap.parse_args()

    res = run_kill_switch_drill(
        warmup_s=args.warmup_s,
        loop_interval_s=args.loop_interval_s,
        timeout_s=args.timeout_s,
    )

    verdict = "PASS" if res.passed else "FAIL"
    print(verdict)
    print(f"Time-to-halt: {res.time_to_halt_s * 1000.0:.1f} ms")
    print(f"Trigger: {res.trigger_source}")
    print(f"Strategy halt latency: {res.strategy_halt_s * 1000.0:.1f} ms")
    print(f"Execution halt latency: {res.execution_halt_s * 1000.0:.1f} ms")
    print(f"Proposals before/after: {res.proposals_before_trigger}/{res.proposals_after_trigger}")
    print(f"Orders before/after: {res.orders_before_trigger}/{res.orders_after_trigger}")
    return 0 if res.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

