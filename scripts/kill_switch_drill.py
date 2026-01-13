"""
Kill-switch drill harness (local, deterministic).

Goal:
- Trigger kill switch (file-backed) while a strategy loop is running
- Confirm the "strategy loop" halts quickly
- Confirm no broker orders can be placed after activation

This is intentionally local-only:
- no Firestore
- no broker network calls
- no k8s required
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from dataclasses import dataclass

# Ensure repo root is on sys.path when invoked as a script:
# `python3 scripts/kill_switch_drill.py`
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.common.kill_switch import get_kill_switch_state
from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager


class _LedgerStub:
    def __init__(self, trades_today: int = 0):
        self._trades_today = trades_today

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        raise AssertionError("ledger writes should not be called in kill-switch drill")


class _PositionsStub:
    def __init__(self, qty: float = 0.0):
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


class _BrokerStub:
    def __init__(self):
        self.place_calls = 0
        self.place_call_times = []

    def place_order(self, *, intent):  # noqa: ARG002
        self.place_calls += 1
        self.place_call_times.append(time.monotonic())
        # Minimal broker-like response
        return {"id": f"order_{self.place_calls}", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


def _write_atomic(path: str, content: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class DrillResult:
    kill_switch_source: str | None
    time_to_strategy_halt_ms: float
    time_to_execution_reject_ms: float
    broker_orders_before: int
    broker_orders_after: int


def run_drill(*, strategy_poll_interval_s: float = 0.01) -> DrillResult:
    # Ensure the drill is testing kill-switch behavior (not agent-mode gating).
    os.environ["AGENT_MODE"] = "LIVE"
    os.environ.pop("EXECUTION_HALTED", None)

    with tempfile.TemporaryDirectory(prefix="agenttrader_kill_switch_drill_") as td:
        kill_file = os.path.join(td, "EXECUTION_HALTED")
        _write_atomic(kill_file, "0\n")
        os.environ["EXECUTION_HALTED_FILE"] = kill_file

        enabled, source = get_kill_switch_state()
        if enabled:
            raise RuntimeError(f"drill invariant violated: kill switch unexpectedly enabled via {source}")

        broker = _BrokerStub()
        risk = RiskManager(
            config=RiskConfig(max_position_qty=10_000, max_daily_trades=10_000, fail_open=True),
            ledger=_LedgerStub(trades_today=0),
            positions=_PositionsStub(qty=0.0),
        )
        engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)

        # For a drill, we only need to prove "post-trigger: no orders can be placed".
        # (In this repo, pre-trade checks may require external dependencies like marketdata heartbeat.)
        broker_before = broker.place_calls

        # Start a tiny "strategy loop" that should stop once kill-switch becomes active.
        strategy_halted_at = {"t": None}

        def _strategy_loop() -> None:
            while True:
                k, _src = get_kill_switch_state()
                if k:
                    strategy_halted_at["t"] = time.monotonic()
                    return
                time.sleep(strategy_poll_interval_s)

        import threading

        th = threading.Thread(target=_strategy_loop, name="kill-switch-drill-strategy", daemon=True)
        th.start()

        # Trigger kill switch and measure:
        t_trigger = time.monotonic()
        _write_atomic(kill_file, "1\n")

        # First post-trigger execution attempt should be rejected immediately and must NOT hit broker.
        post_start = time.monotonic()
        post = engine.execute_intent(
            intent=OrderIntent(
                strategy_id="kill-switch-drill",
                broker_account_id="acct_drill",
                symbol="SPY",
                side="buy",
                qty=1,
            )
        )
        post_end = time.monotonic()

        if post.status != "rejected" or (post.risk is None) or post.risk.reason != "kill_switch_enabled":
            raise RuntimeError(
                f"expected post-kill order to be rejected with kill_switch_enabled; "
                f"got status={post.status} risk_reason={getattr(post.risk, 'reason', None)} message={post.message}"
            )

        # Wait briefly for the strategy loop to observe the kill-switch.
        th.join(timeout=2.0)
        if strategy_halted_at["t"] is None:
            raise RuntimeError("strategy loop did not halt within 2s after kill-switch trigger")

        # Confirm no new broker orders were placed after the kill switch.
        broker_after = broker.place_calls
        if broker_after != broker_before:
            raise RuntimeError(
                f"broker calls changed after kill-switch activation: before={broker_before} after={broker_after}"
            )

        # Derive timings.
        time_to_strategy_halt_ms = (float(strategy_halted_at["t"]) - float(t_trigger)) * 1000.0
        # "Execution reject latency" = wall time of the call post-trigger, plus any delay since trigger
        # due to scheduling (kept explicit for audit).
        time_to_execution_reject_ms = (post_end - t_trigger) * 1000.0

        # Emit confirmation logs (single-line key=value for easy grepping).
        k2, src2 = get_kill_switch_state()
        print(f"[kill_switch_drill] kill_switch_triggered enabled={k2} source={src2}")
        print(f"[kill_switch_drill] strategy_halted time_to_halt_ms={time_to_strategy_halt_ms:.2f}")
        print(
            "[kill_switch_drill] execution_rejected "
            f"time_since_trigger_ms={time_to_execution_reject_ms:.2f} "
            f"call_duration_ms={(post_end - post_start) * 1000.0:.2f} "
            f"risk_reason={post.risk.reason}"
        )
        print(
            "[kill_switch_drill] broker_calls "
            f"orders_before={broker_before} orders_after={broker_after} "
            f"no_new_orders={'true' if broker_after == broker_before else 'false'}"
        )

        return DrillResult(
            kill_switch_source=src2,
            time_to_strategy_halt_ms=time_to_strategy_halt_ms,
            time_to_execution_reject_ms=time_to_execution_reject_ms,
            broker_orders_before=broker_before,
            broker_orders_after=broker_after,
        )


if __name__ == "__main__":
    run_drill()

