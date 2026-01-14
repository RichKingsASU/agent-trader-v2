#!/usr/bin/env python3
"""
Kill-switch drill (local, no external services).

Goals:
- Trigger kill switch via file toggle (EXECUTION_HALTED_FILE).
- Confirm "execution halts": execution attempts get rejected; broker is never called.
- Measure stop latency:
  - Detection latency: flip -> first kill-switch-enabled observation.
  - Strategy-loop halt latency: flip -> loop exits on next check interval.

This script is intentionally self-contained and avoids Firestore/broker/NATS/network.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass

from backend.common.kill_switch import ExecutionHaltedError, get_kill_switch_state, require_live_mode
from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager


def _write_text_atomic(path: str, content: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class DrillResult:
    passed: bool
    detection_latency_ms: float
    strategy_halt_latency_ms: float
    broker_calls_after_kill: int
    kill_switch_source: str | None


class _BrokerStub:
    def __init__(self) -> None:
        self.place_calls = 0

    def place_order(self, *, intent):  # noqa: ARG002
        self.place_calls += 1
        return {"id": "order_1", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str):  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


class _LedgerStub:
    def __init__(self, trades_today: int = 0) -> None:
        self._trades_today = trades_today

    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
        return int(self._trades_today)

    def write_fill(self, *, intent, broker, broker_order, fill):  # noqa: ARG002
        raise AssertionError("ledger writes should not be called in this drill")


class _PositionsStub:
    def __init__(self, qty: float) -> None:
        self._qty = float(qty)

    def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
        return float(self._qty)


def _clear_kill_switch_env() -> None:
    for k in (
        "EXECUTION_HALTED",
        "EXECUTION_HALTED_FILE",
        "EXEC_KILL_SWITCH",
        "EXEC_KILL_SWITCH_FILE",
    ):
        os.environ.pop(k, None)


def run_drill(*, strategy_check_interval_s: float = 1.0, max_wait_s: float = 5.0) -> DrillResult:
    """
    Run a local drill using the file-based kill switch.

    strategy_check_interval_s:
      Models a strategy/event loop that checks the kill switch on an interval.
      (e.g., `options_bot` checks once per ~1s in its main loop.)
    """
    _clear_kill_switch_env()

    fd, path = tempfile.mkstemp(prefix="agenttrader_kill_switch_", suffix=".txt")
    os.close(fd)
    try:
        _write_text_atomic(path, "0\n")
        os.environ["EXECUTION_HALTED_FILE"] = path

        # Sanity check: kill switch starts disabled.
        enabled0, _src0 = get_kill_switch_state()
        if enabled0:
            return DrillResult(
                passed=False,
                detection_latency_ms=0.0,
                strategy_halt_latency_ms=0.0,
                broker_calls_after_kill=-1,
                kill_switch_source=_src0,
            )

        # ---- Trigger kill switch and measure detection latency ----
        t_flip = time.perf_counter()
        _write_text_atomic(path, "1\n")

        enabled = False
        source: str | None = None
        while (time.perf_counter() - t_flip) < max_wait_s:
            enabled, source = get_kill_switch_state()
            if enabled:
                break
        t_detect = time.perf_counter()
        detection_ms = (t_detect - t_flip) * 1000.0

        # ---- "Strategy loop" halt latency (models periodic checks) ----
        # We model an existing loop that checks on an interval and exits when kill flips.
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) < max_wait_s:
            k, _s = get_kill_switch_state()
            if k:
                break
            time.sleep(max(0.0, float(strategy_check_interval_s)))
        t_strategy_halt = time.perf_counter()
        strategy_halt_ms = (t_strategy_halt - t_flip) * 1000.0

        # ---- Confirm: require_live_mode refuses operations immediately ----
        refused_ok = False
        try:
            require_live_mode(operation="kill-switch-drill.require_live_mode")
        except ExecutionHaltedError:
            refused_ok = True

        # ---- Confirm: execution engine rejects and broker is not called ----
        broker = _BrokerStub()
        risk = RiskManager(
            config=RiskConfig(max_position_qty=100, max_daily_trades=50, fail_open=True),
            ledger=_LedgerStub(trades_today=0),
            positions=_PositionsStub(qty=0),
        )
        engine = ExecutionEngine(broker=broker, risk=risk, dry_run=False)
        result = engine.execute_intent(
            intent=OrderIntent(
                strategy_id="s1",
                broker_account_id="acct1",
                symbol="SPY",
                side="buy",
                qty=1,
            )
        )
        engine_ok = (result.status == "rejected") and (getattr(result.risk, "reason", None) == "kill_switch_enabled")
        broker_ok = broker.place_calls == 0

        passed = bool(enabled) and refused_ok and engine_ok and broker_ok
        return DrillResult(
            passed=passed,
            detection_latency_ms=float(detection_ms),
            strategy_halt_latency_ms=float(strategy_halt_ms),
            broker_calls_after_kill=int(broker.place_calls),
            kill_switch_source=source,
        )
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def main() -> int:
    res = run_drill(strategy_check_interval_s=float(os.getenv("DRILL_STRATEGY_CHECK_INTERVAL_S") or "1.0"))
    print("kill_switch_drill_result")
    print(f"PASS={str(bool(res.passed)).lower()}")
    print(f"time_to_halt_detection_ms={res.detection_latency_ms:.2f}")
    print(f"time_to_halt_strategy_loop_ms={res.strategy_halt_latency_ms:.2f}")
    print(f"kill_switch_source={res.kill_switch_source}")
    print(f"broker_place_calls_after_kill={res.broker_calls_after_kill}")
    return 0 if res.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

