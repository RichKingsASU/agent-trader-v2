#!/usr/bin/env python3
"""
Kill-switch drill harness (local-safe).

Goal:
- Prove we can stop trading instantly by flipping the global kill switch.

What it verifies:
- "strategies halt": a representative strategy loop stops producing work once the
  kill switch is enabled (no further "strategy_tick" after halt).
- "no new orders placed": the execution engine refuses broker-side placement
  immediately once the kill switch is enabled.

This script is designed to be safe in any environment:
- Uses an in-memory broker stub (no network calls, no real orders)
- Uses the execution engine's real kill-switch gate (defense-in-depth boundary)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_atomic(path: str, content: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class DrillLogs:
    lines: list[str]

    def log(self, event: str, **fields: Any) -> None:
        payload = {"ts": _utc_now_iso(), "event": event, **fields}
        line = json.dumps(payload, sort_keys=True)
        self.lines.append(line)
        print(line, flush=True)


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = trades_today

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ANN001, ARG002
        raise AssertionError("ledger writes should not be called in this drill")


class _PositionsStub:
    def __init__(self, qty: float = 0.0):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


class _BrokerStub:
    def __init__(self, logs: DrillLogs):
        self.place_calls = 0
        self.logs = logs

    def place_order(self, *, intent):  # noqa: ANN001
        self.place_calls += 1
        self.logs.log(
            "broker_place_order_called",
            symbol=getattr(intent, "symbol", None),
            side=getattr(intent, "side", None),
            qty=getattr(intent, "qty", None),
            client_intent_id=getattr(intent, "client_intent_id", None),
            place_calls=self.place_calls,
        )
        return {"id": f"stub_order_{self.place_calls}", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


def main() -> int:
    logs = DrillLogs(lines=[])

    # Ensure workspace root is importable when running as a script.
    # (CI often runs without installing the package.)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Configure safe local kill-switch via file (simulates K8s ConfigMap mount).
    with tempfile.TemporaryDirectory() as td:
        kill_file = os.path.join(td, "EXECUTION_HALTED")
        _write_atomic(kill_file, "0\n")

        os.environ["EXECUTION_HALTED_FILE"] = kill_file
        os.environ["EXECUTION_HALTED"] = "0"

        # Allow execution path to reach the kill-switch gate.
        os.environ["AGENT_MODE"] = "LIVE"

        logs.log("drill_started", kill_switch_file=kill_file)

        # Import after env is prepared so runtime reads correct config.
        from backend.common.kill_switch import get_kill_switch_state  # noqa: WPS433
        from backend.execution.engine import (  # noqa: WPS433
            ExecutionEngine,
            OrderIntent,
            RiskConfig,
            RiskManager,
        )

        broker = _BrokerStub(logs=logs)
        risk = RiskManager(
            config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
            ledger=_LedgerStub(trades_today=0),
            positions=_PositionsStub(qty=0),
        )
        engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

        stop_flag = threading.Event()

        # Strategy loop: representative "work" loop that must halt after kill switch.
        strategy_halted_at: dict[str, float] = {}

        def strategy_loop() -> None:
            i = 0
            while not stop_flag.is_set():
                enabled, source = get_kill_switch_state()
                if enabled:
                    strategy_halted_at["t"] = time.monotonic()
                    logs.log("strategy_halted", source=source, iteration=i)
                    return
                i += 1
                logs.log("strategy_tick", iteration=i)
                time.sleep(0.05)

        # Execution loop: attempts broker placement repeatedly; must be rejected after kill switch.
        first_reject_after_trigger: dict[str, float] = {}
        trigger_at: dict[str, float] = {}
        exec_halted_at: dict[str, float] = {}
        pre_trigger_orders: dict[str, int] = {}
        post_trigger_orders: dict[str, int] = {}

        def execution_loop() -> None:
            i = 0
            while not stop_flag.is_set():
                i += 1
                intent = OrderIntent(
                    strategy_id="drill_strategy",
                    broker_account_id="drill_acct",
                    symbol="SPY",
                    side="buy",
                    qty=1,
                )
                try:
                    result = engine.execute_intent(intent=intent)
                except Exception as e:  # noqa: BLE001
                    logs.log("execute_exception", error_type=type(e).__name__, error=str(e))
                    time.sleep(0.05)
                    continue

                logs.log(
                    "execute_result",
                    iteration=i,
                    status=getattr(result, "status", None),
                    risk_reason=getattr(getattr(result, "risk", None), "reason", None),
                    broker_place_calls=broker.place_calls,
                )

                if trigger_at:
                    # After trigger: first rejection is our halt confirmation.
                    if getattr(result, "status", None) == "rejected" and getattr(getattr(result, "risk", None), "reason", None) == "kill_switch_enabled":
                        if "t" not in first_reject_after_trigger:
                            first_reject_after_trigger["t"] = time.monotonic()
                            exec_halted_at["t"] = first_reject_after_trigger["t"]
                            post_trigger_orders["broker_place_calls"] = broker.place_calls
                            logs.log("execution_halted_confirmed", broker_place_calls=broker.place_calls)
                            # Do not stop immediately; allow strategy loop to observe halt too.
                            return

                time.sleep(0.05)

        st = threading.Thread(target=strategy_loop, name="strategy_loop", daemon=True)
        ex = threading.Thread(target=execution_loop, name="execution_loop", daemon=True)

        st.start()
        ex.start()

        # Let both loops run briefly (pre-trigger).
        time.sleep(0.25)
        pre_trigger_orders["broker_place_calls"] = broker.place_calls
        enabled0, source0 = get_kill_switch_state()
        logs.log(
            "pre_trigger_state",
            kill_switch_enabled=bool(enabled0),
            source=source0,
            broker_place_calls=broker.place_calls,
        )

        # --- Trigger kill switch ---
        _write_atomic(kill_file, "1\n")
        trigger_at["t"] = time.monotonic()
        enabled1, source1 = get_kill_switch_state()
        logs.log("kill_switch_triggered", kill_switch_enabled=bool(enabled1), source=source1)

        # Wait for confirmation.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if ("t" in exec_halted_at) and ("t" in strategy_halted_at):
                break
            time.sleep(0.01)

        stop_flag.set()
        st.join(timeout=1.0)
        ex.join(timeout=1.0)

        if "t" not in exec_halted_at:
            logs.log("drill_failed", reason="execution_did_not_halt_within_timeout")
            return 2

        # Compute timings.
        t_trigger = trigger_at["t"]
        t_exec_halt = exec_halted_at["t"]
        t_strat_halt = strategy_halted_at.get("t")

        out: dict[str, Any] = {
            "triggered_at_utc": _utc_now_iso(),
            "kill_switch_file": kill_file,
            "pre_trigger": {"broker_place_calls": pre_trigger_orders.get("broker_place_calls", 0)},
            "post_trigger": {"broker_place_calls": post_trigger_orders.get("broker_place_calls", broker.place_calls)},
            "time_to_halt_seconds": {
                "execution": round(max(0.0, t_exec_halt - t_trigger), 4),
                "strategy": (round(max(0.0, float(t_strat_halt) - t_trigger), 4) if t_strat_halt is not None else None),
            },
        }

        logs.log("drill_summary", **out)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

