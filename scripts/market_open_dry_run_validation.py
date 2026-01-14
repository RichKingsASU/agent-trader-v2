#!/usr/bin/env python3
"""
Market Open Dry-Run Validation Harness

Goal:
- "Replay last market open" by fetching historical 1-minute bars for the most recent
  NYSE session open and simulating the first N minutes (default: 30).
- Validate:
  - data ingestion (market data fetch + completeness checks)
  - strategy signals (strategy evaluation executes successfully over the window)
  - order gating (execution engine returns dry_run / never calls broker)

This script is intentionally **read-only** and **paper-safe**.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.time.nyse_time import UTC, market_open_dt, previous_close, to_utc


DEFAULT_SYMBOLS = [
    # SectorRotationStrategy universe + crash detector + safe haven
    "SPY",
    "SHV",
    "XLK",
    "XLE",
    "XLF",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLB",
    "XLU",
    "XLRE",
]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    blockers: list[str]
    details: dict[str, Any]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_list(raw: str) -> list[str]:
    parts = [p.strip().upper() for p in (raw or "").split(",")]
    return [p for p in parts if p]


def _most_recent_open_window(*, minutes: int) -> tuple[datetime, datetime]:
    # previous_close() returns NY tz for the most recent session close at/before now.
    last_close_ny = previous_close(datetime.now(tz=UTC))
    session_date_ny = last_close_ny.date()
    open_ny = market_open_dt(session_date_ny)
    start_utc = to_utc(open_ny)
    end_utc = start_utc + timedelta(minutes=int(minutes))
    return start_utc, end_utc


def _fetch_alpaca_minute_bars(
    *,
    symbols: list[str],
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    blockers: list[str] = []

    api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
    api_secret = (os.getenv("APCA_API_SECRET_KEY") or "").strip()
    if not api_key or not api_secret:
        blockers.append("Missing Alpaca credentials (APCA_API_KEY_ID / APCA_API_SECRET_KEY); cannot replay last open.")
        return {}, blockers

    try:
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
        from alpaca.data.requests import StockBarsRequest  # type: ignore
        from alpaca.data.timeframe import TimeFrame  # type: ignore
    except Exception as e:  # pragma: no cover
        blockers.append(f"Missing dependency for historical bars (alpaca-py). Import failed: {type(e).__name__}: {e}")
        return {}, blockers

    client = StockHistoricalDataClient(api_key, api_secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=to_utc(start_utc),
        end=to_utc(end_utc),
    )

    try:
        bars = client.get_stock_bars(req)
    except Exception as e:
        blockers.append(f"Alpaca historical bars fetch failed: {type(e).__name__}: {e}")
        return {}, blockers

    out: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols:
        rows = []
        try:
            for b in bars[sym]:
                rows.append(
                    {
                        "ts": to_utc(b.timestamp),
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": int(b.volume),
                    }
                )
        except Exception:
            rows = []
        rows.sort(key=lambda r: r["ts"])
        out[sym] = rows
    return out, blockers


def _validate_ingestion_completeness(
    *,
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    symbols: list[str],
    start_utc: datetime,
    end_utc: datetime,
    minutes: int,
) -> ValidationResult:
    blockers: list[str] = []
    details: dict[str, Any] = {}

    expected = [start_utc + timedelta(minutes=i) for i in range(int(minutes))]
    expected_set = {int(t.timestamp()) for t in expected}

    per_symbol = {}
    missing_total = 0
    expected_total = len(symbols) * len(expected)

    for sym in symbols:
        rows = bars_by_symbol.get(sym) or []
        seen = {int(to_utc(r["ts"]).timestamp()) for r in rows if isinstance(r.get("ts"), datetime)}
        missing = sorted(expected_set - seen)
        missing_total += len(missing)

        per_symbol[sym] = {
            "bars": len(rows),
            "missing_minutes": len(missing),
            "first_ts": _iso(rows[0]["ts"]) if rows else None,
            "last_ts": _iso(rows[-1]["ts"]) if rows else None,
        }

        # Hard fail if completely missing a symbol.
        if len(rows) == 0:
            blockers.append(f"Missing bars for symbol {sym} in replay window (no data returned).")

    missing_ratio = (missing_total / expected_total) if expected_total else 1.0
    details["window_utc"] = {"start": _iso(start_utc), "end": _iso(end_utc), "minutes": int(minutes)}
    details["expected_bars_per_symbol"] = int(minutes)
    details["missing_ratio"] = missing_ratio
    details["per_symbol"] = per_symbol

    # Tolerate small gaps (provider quirks), but fail if gaps are meaningful.
    if missing_ratio > 0.10:
        blockers.append(
            f"Market data incomplete: missing {missing_total}/{expected_total} expected 1m bars "
            f"({missing_ratio:.1%} missing) across symbols."
        )

    ok = len(blockers) == 0
    return ValidationResult(ok=ok, blockers=blockers, details=details)


def _run_strategy_and_gate_orders(
    *,
    start_utc: datetime,
    end_utc: datetime,
    minutes: int,
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    symbols: list[str],
) -> ValidationResult:
    blockers: list[str] = []
    details: dict[str, Any] = {"signals": [], "gating": {}}

    # Strategy under test: SectorRotationStrategy (runs without DB dependencies).
    from functions.strategies.sector_rotation import SectorRotationStrategy
    from functions.strategies.base_strategy import SignalType as FnSignalType

    strat = SectorRotationStrategy(
        config={
            # Force the strategy to "rebalance" on the first evaluation in this window.
            # Subsequent minutes are expected HOLD in the same day (days granularity).
            "rebalance_frequency_days": 1,
            "lookback_days": 20,
            "num_top_sectors": 3,
            "crash_threshold": -0.05,
        }
    )

    # Execution engine (dry-run only) + hard "never call broker" stub.
    from backend.execution.engine import ExecutionEngine, OrderIntent, RiskConfig, RiskManager

    class _BrokerNever:
        place_calls = 0
        cancel_calls = 0
        status_calls = 0

        def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:  # noqa: ARG002
            self.place_calls += 1
            raise AssertionError("Broker should never be called during dry_run validation")

        def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:  # noqa: ARG002
            self.cancel_calls += 1
            raise AssertionError("Broker should never be called during dry_run validation")

        def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:  # noqa: ARG002
            self.status_calls += 1
            raise AssertionError("Broker should never be called during dry_run validation")

    class _LedgerStub:
        def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int:  # noqa: ARG002
            return 0

    class _PositionsStub:
        def get_position_qty(self, *, symbol: str) -> float:  # noqa: ARG002
            return 0.0

    risk = RiskManager(
        config=RiskConfig(max_position_qty=1_000_000, max_daily_trades=1_000_000, fail_open=True),
        ledger=_LedgerStub(),
        positions=_PositionsStub(),
    )
    broker = _BrokerNever()
    engine = ExecutionEngine(broker=broker, risk=risk, dry_run=True)

    expected_times = [start_utc + timedelta(minutes=i) for i in range(int(minutes))]

    # Pre-index bars for quick lookup.
    by_sym_ts: dict[str, dict[int, dict[str, Any]]] = {}
    for sym in symbols:
        m: dict[int, dict[str, Any]] = {}
        for r in (bars_by_symbol.get(sym) or []):
            ts = r.get("ts")
            if isinstance(ts, datetime):
                m[int(to_utc(ts).timestamp())] = r
        by_sym_ts[sym] = m

    prev_price: dict[str, float | None] = {s: None for s in symbols}
    account_snapshot = {"equity": "100000", "buying_power": "100000", "cash": "100000", "positions": []}

    order_results: list[dict[str, Any]] = []

    def _emit_intent_for_symbol(sym: str, side: str, *, trace_id: str) -> None:
        intent = OrderIntent(
            strategy_id="SectorRotationStrategy",
            broker_account_id="paper",
            symbol=sym,
            side=side,
            qty=1,
            metadata={"trace_id": trace_id, "replay_window_start": _iso(start_utc)},
        )
        res = engine.execute_intent(intent=intent)
        order_results.append(
            {
                "symbol": sym,
                "side": side,
                "status": res.status,
                "risk_reason": res.risk.reason,
            }
        )
        if res.status == "placed":
            blockers.append(f"Order gating failure: intent for {sym} returned status=placed in dry-run.")

    for i, t in enumerate(expected_times):
        ts_key = int(t.timestamp())
        market_data: dict[str, dict[str, Any]] = {}
        missing_syms = 0
        for sym in symbols:
            row = by_sym_ts.get(sym, {}).get(ts_key)
            if row is None:
                missing_syms += 1
                continue
            px = float(row.get("close") or 0.0)
            market_data[sym] = {"price": px, "previous_price": prev_price.get(sym)}
            prev_price[sym] = px

        # If this minute is missing too much data, skip evaluation but record it as a blocker.
        if missing_syms > max(2, int(0.25 * len(symbols))):
            blockers.append(f"Strategy input incomplete at {_iso(t)}: missing {missing_syms}/{len(symbols)} symbols.")
            continue

        sig = strat.evaluate(market_data=market_data, account_snapshot=account_snapshot, regime=None)
        details["signals"].append(
            {
                "ts": _iso(t),
                "signal_type": getattr(sig.signal_type, "value", str(sig.signal_type)),
                "confidence": float(getattr(sig, "confidence", 0.0) or 0.0),
                "reasoning": str(getattr(sig, "reasoning", ""))[:500],
            }
        )

        # Translate strategy signal → representative order intents (for gating validation only).
        trace_id = f"market_open_dry_run_{_iso(start_utc)}_{i}"
        if sig.signal_type == FnSignalType.BUY:
            ta = (getattr(sig, "metadata", None) or {}).get("target_allocation")
            if isinstance(ta, dict) and ta:
                for sym in sorted(ta.keys()):
                    _emit_intent_for_symbol(sym, "buy", trace_id=trace_id)
            else:
                _emit_intent_for_symbol("SPY", "buy", trace_id=trace_id)
        elif sig.signal_type == FnSignalType.SELL:
            _emit_intent_for_symbol("SPY", "sell", trace_id=trace_id)
        elif sig.signal_type == FnSignalType.CLOSE_ALL:
            # Represent as "sell SPY" and "buy SHV" (cash proxy) to exercise gating paths.
            _emit_intent_for_symbol("SPY", "sell", trace_id=trace_id)
            _emit_intent_for_symbol("SHV", "buy", trace_id=trace_id)

    details["gating"] = {
        "dry_run": True,
        "orders_simulated": len(order_results),
        "broker_place_calls": int(getattr(broker, "place_calls", 0)),
        "results_sample": order_results[:20],
    }

    if getattr(broker, "place_calls", 0) != 0:
        blockers.append("Order gating failure: broker.place_order was called during dry-run validation.")

    ok = len(blockers) == 0
    return ValidationResult(ok=ok, blockers=blockers, details=details)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay last market open first N minutes and validate ingestion/signals/gating.")
    p.add_argument("--minutes", type=int, default=30, help="Minutes after open to simulate (default: 30).")
    p.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols to fetch (default: sector rotation universe).",
    )
    args = p.parse_args(argv)

    minutes = max(1, int(args.minutes))
    symbols = _env_list(args.symbols)
    if not symbols:
        symbols = list(DEFAULT_SYMBOLS)

    start_utc, end_utc = _most_recent_open_window(minutes=minutes)

    all_blockers: list[str] = []
    details: dict[str, Any] = {
        "window_utc": {"start": _iso(start_utc), "end": _iso(end_utc), "minutes": minutes},
        "symbols": symbols,
    }

    bars_by_symbol, fetch_blockers = _fetch_alpaca_minute_bars(symbols=symbols, start_utc=start_utc, end_utc=end_utc)
    all_blockers.extend(fetch_blockers)

    # Validate ingestion (market data availability/completeness).
    if bars_by_symbol:
        ingest = _validate_ingestion_completeness(
            bars_by_symbol=bars_by_symbol, symbols=symbols, start_utc=start_utc, end_utc=end_utc, minutes=minutes
        )
        details["ingestion"] = ingest.details
        all_blockers.extend(ingest.blockers)
    else:
        details["ingestion"] = {"status": "skipped", "reason": "no_bars"}

    # Validate strategy signals + order gating only if we have data to drive it.
    if bars_by_symbol:
        sg = _run_strategy_and_gate_orders(
            start_utc=start_utc,
            end_utc=end_utc,
            minutes=minutes,
            bars_by_symbol=bars_by_symbol,
            symbols=symbols,
        )
        details["strategy_and_gating"] = sg.details
        all_blockers.extend(sg.blockers)
    else:
        details["strategy_and_gating"] = {"status": "skipped", "reason": "no_bars"}

    ok = len(all_blockers) == 0

    sys.stdout.write(f"RESULT: {'PASS' if ok else 'FAIL'}\n")
    sys.stdout.write(f"Window (UTC): {_iso(start_utc)} → {_iso(end_utc)}\n")
    sys.stdout.write(f"Symbols: {', '.join(symbols)}\n")
    sys.stdout.write("\n")
    if all_blockers:
        sys.stdout.write("Blockers:\n")
        for b in all_blockers:
            sys.stdout.write(f"- {b}\n")
    else:
        sys.stdout.write("Blockers:\n- (none)\n")
    sys.stdout.write("\n")

    # Optional: emit a tiny JSON payload for CI/log parsing.
    sys.stdout.write("DETAILS_JSON_START\n")
    try:
        import json

        sys.stdout.write(json.dumps({"ok": ok, "blockers": all_blockers, "details": details}, default=str) + "\n")
    except Exception:
        sys.stdout.write('{"ok": false, "blockers": ["failed to serialize details"]}\n')
    sys.stdout.write("DETAILS_JSON_END\n")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

