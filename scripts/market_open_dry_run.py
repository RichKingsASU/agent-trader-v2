#!/usr/bin/env python3
"""
ROLE: Market Open Dry-Run Agent

Goal:
- Simulate tomorrow’s first 30 minutes by replaying the last trading day’s first 30 minutes.

Checks:
- Data ingestion works (can fetch real 1m bars for the window)
- Strategies emit signals (strategy produces decisions over the replay window)
- Orders are gated correctly (execution engine returns dry_run, no broker side effects)

Output:
- PASS / FAIL
- Any blockers
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import requests


def _ensure_repo_on_path() -> None:
    # Allow running from repo root without manual PYTHONPATH.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _set_safe_defaults() -> None:
    # Many modules in this repo enforce these guards at import time for safety.
    os.environ.setdefault("AGENT_MODE", "OBSERVE")
    os.environ.setdefault("TRADING_MODE", "paper")
    # Force dry-run at the execution layer even if local env differs.
    os.environ.setdefault("EXEC_DRY_RUN", "1")


_ensure_repo_on_path()
_set_safe_defaults()


from backend.streams.alpaca_env import load_alpaca_env  # noqa: E402
from backend.time.nyse_time import UTC, market_open_dt, previous_close, to_utc, utc_now  # noqa: E402
from backend.execution.engine import (  # noqa: E402
    DryRunBroker,
    ExecutionEngine,
    OrderIntent,
    RiskConfig,
    RiskManager,
)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_symbols() -> List[str]:
    raw = (
        os.getenv("DRY_RUN_SYMBOLS")
        or os.getenv("ALPACA_SYMBOLS")
        or os.getenv("MONITORED_SYMBOLS")
        or "SPY"
    )
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class DryRunResult:
    status: str  # PASS|FAIL
    blockers: List[str]
    details: Dict[str, Any]


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class FlowEvent:
    ts: datetime
    total_value: float


def make_decision(bars: List[Bar], flow_events: List[FlowEvent]) -> Dict[str, Any]:
    """
    Strategy decision logic (mirrors backend.strategy_engine.strategies.naive_flow_trend).
    Implemented locally to keep this script runnable without DB deps (asyncpg).
    """
    if not bars:
        return {"action": "flat", "reason": "No recent bar data.", "signal_payload": {}}

    closes = [bar.close for bar in bars]
    sma = sum(closes) / len(closes)
    last_close = closes[0]

    call_value = sum(event.total_value for event in flow_events if event.total_value > 0)
    put_value = sum(event.total_value for event in flow_events if event.total_value < 0)
    flow_imbalance = call_value + put_value

    if last_close > sma and flow_imbalance > 0:
        action = "buy"
        reason = f"Price ({last_close:.2f}) is above SMA ({sma:.2f}) and flow is bullish ({flow_imbalance:.2f})."
    else:
        action = "flat"
        reason = f"Price ({last_close:.2f}) is not decisively above SMA ({sma:.2f}) or flow is not bullish ({flow_imbalance:.2f})."

    return {
        "action": action,
        "reason": reason,
        "signal_payload": {"sma": sma, "last_close": last_close, "flow_imbalance": flow_imbalance},
    }


def _fetch_bars_1m(*, symbol: str, start_utc: datetime, end_utc: datetime, feed: str) -> List[dict[str, Any]]:
    alpaca = load_alpaca_env(require_keys=True)
    base = alpaca.data_stocks_base_v2.rstrip("/")
    url = f"{base}/{symbol}/bars"
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}
    params = {
        "timeframe": "1Min",
        "start": _iso_z(start_utc),
        "end": _iso_z(end_utc),
        "limit": 10000,
        "feed": feed,
        "adjustment": "all",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return list(r.json().get("bars", []) or [])


def _bars_from_alpaca_payload(rows: List[dict[str, Any]]) -> List[Bar]:
    out: List[Bar] = []
    for b in rows:
        try:
            # Alpaca uses RFC3339 timestamps in field "t".
            ts = str(b.get("t") or "").strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts).astimezone(UTC)
            out.append(
                Bar(
                    ts=dt,
                    open=float(b.get("o")),
                    high=float(b.get("h")),
                    low=float(b.get("l")),
                    close=float(b.get("c")),
                    volume=int(b.get("v") or 0),
                )
            )
        except Exception:
            continue
    # Alpaca typically returns ascending; normalize to ascending for replay.
    out.sort(key=lambda x: x.ts)
    return out


def _build_flow_proxy(*, recent_bars_desc: List[Bar], max_events: int = 10) -> List[FlowEvent]:
    """
    The built-in naive strategy expects options flow events; for this dry-run we
    synthesize a stable, positive flow signal derived from volume.

    This is *not* intended to model real flow—only to exercise the signal path
    deterministically in environments without options flow ingestion.
    """
    evs: List[FlowEvent] = []
    for b in recent_bars_desc[:max_events]:
        # Positive notional proxy.
        notional = float(b.close) * float(max(0, int(b.volume)))
        evs.append(FlowEvent(ts=b.ts, total_value=notional))
    return evs


class _StubLedger:
    def count_trades_today(self, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        return 0


class _StubPositions:
    def get_position_qty(self, *args: Any, **kwargs: Any) -> float:  # noqa: ARG002
        return 0.0


def run() -> DryRunResult:
    blockers: List[str] = []
    details: Dict[str, Any] = {}

    # Window: last trading day's first 30 minutes.
    now = utc_now()
    last_close_ny = previous_close(now)
    last_trading_day_ny = last_close_ny.date()

    open_ny = market_open_dt(last_trading_day_ny)
    start_utc = to_utc(open_ny)
    end_utc = start_utc + timedelta(minutes=30)

    details["window"] = {
        "last_trading_day_ny": str(last_trading_day_ny),
        "open_ny": open_ny.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
    }

    symbols = _env_symbols()
    feed = (os.getenv("ALPACA_FEED") or os.getenv("ALPACA_DATA_FEED") or "iex").strip().lower() or "iex"
    details["symbols"] = symbols
    details["feed"] = feed

    # --- 1) Ingestion: fetch real bars ---
    ingested: Dict[str, List[Bar]] = {}
    try:
        for sym in symbols:
            raw = _fetch_bars_1m(symbol=sym, start_utc=start_utc, end_utc=end_utc, feed=feed)
            bars = _bars_from_alpaca_payload(raw)
            ingested[sym] = bars
    except Exception as e:
        blockers.append(f"data_ingestion_failed: {type(e).__name__}: {e}")
        return DryRunResult(status="FAIL", blockers=blockers, details=details)

    details["ingestion"] = {sym: {"bars": len(bars)} for sym, bars in ingested.items()}

    # Basic sanity: expect ~30 1m bars per symbol (allow gaps).
    for sym, bars in ingested.items():
        if len(bars) < 10:
            blockers.append(f"insufficient_bars: symbol={sym} bars={len(bars)} expected~30")

    # --- 2) Strategy: replay minute-by-minute, emit signals ---
    signals: List[dict[str, Any]] = []
    buy_signals: List[dict[str, Any]] = []

    for sym, bars_asc in ingested.items():
        if not bars_asc:
            continue
        # Replay in chronological order; decision at each minute is based on bars-so-far.
        for i in range(len(bars_asc)):
            upto = bars_asc[: i + 1]
            # Strategy expects newest-first list (repo convention in DB fetches).
            bars_desc = list(reversed(upto))
            flow = _build_flow_proxy(recent_bars_desc=bars_desc)
            decision = make_decision(bars_desc, flow)
            sig = {
                "symbol": sym,
                "ts": bars_asc[i].ts.isoformat(),
                "action": str(decision.get("action") or "flat"),
                "reason": str(decision.get("reason") or ""),
                "signal_payload": decision.get("signal_payload") or {},
            }
            signals.append(sig)
            if sig["action"].lower() in {"buy", "sell"}:
                buy_signals.append(sig)

    details["strategy"] = {
        "signals_total": len(signals),
        "trade_signals_total": len(buy_signals),
    }

    if not signals:
        blockers.append("strategy_no_signals_emitted")
    # We need at least one trade-like signal to exercise execution gating.
    if not buy_signals:
        blockers.append("strategy_emitted_no_buy_sell_signals (cannot exercise execution gating)")

    # --- 3) Execution: ensure orders are gated (dry_run) ---
    # Use stubbed providers to avoid external dependencies (Firestore/Postgres) during dry-run.
    risk = RiskManager(config=RiskConfig(max_position_qty=1_000_000.0, max_daily_trades=1_000_000, fail_open=True), ledger=_StubLedger(), positions=_StubPositions())
    engine = ExecutionEngine(broker=DryRunBroker(), risk=risk, broker_name="dryrun", dry_run=True)

    exec_results: List[dict[str, Any]] = []
    for sig in buy_signals[:5]:
        intent = OrderIntent(
            strategy_id="dryrun_strategy",
            broker_account_id="dryrun_account",
            symbol=str(sig["symbol"]),
            side=str(sig["action"]).lower(),
            qty=float(os.getenv("DRY_RUN_QTY") or "1"),
            order_type="market",
            time_in_force="day",
            metadata={
                "run_id": "market_open_dry_run",
                "trace_id": "market_open_dry_run",
                "correlation_id": "market_open_dry_run",
                # Provide a tenant id so downstream optional paths can stay deterministic.
                "tenant_id": os.getenv("TENANT_ID") or "dryrun_tenant",
                "uid": os.getenv("EXEC_UID") or "dryrun_user",
                "notional_usd": float(sig.get("signal_payload", {}).get("last_close") or 0.0),
            },
        )
        res = engine.execute_intent(intent=intent)
        exec_results.append(
            {
                "symbol": intent.symbol,
                "side": intent.side,
                "status": res.status,
                "risk_allowed": bool(res.risk.allowed),
                "risk_reason": res.risk.reason,
                "message": res.message,
            }
        )

    details["execution"] = exec_results

    # Validate gating outcome: at least one intent should be dry_run with risk allowed.
    if exec_results:
        ok_any = any(r["status"] == "dry_run" and r["risk_allowed"] is True for r in exec_results)
        if not ok_any:
            blockers.append("execution_not_dry_run_or_risk_denied (expected dry_run with allowed risk)")
    else:
        blockers.append("execution_not_exercised (no trade signals to convert into intents)")

    status = "PASS" if not blockers else "FAIL"
    return DryRunResult(status=status, blockers=blockers, details=details)


def main(argv: List[str] | None = None) -> int:  # noqa: ARG001
    try:
        result = run()
    except SystemExit as e:
        # Surface any guardrail exits clearly.
        code = int(getattr(e, "code", 1) or 1)
        sys.stdout.write("FAIL\n")
        sys.stdout.write(f"blocker: SystemExit({code})\n")
        return code
    except Exception as e:
        sys.stdout.write("FAIL\n")
        sys.stdout.write(f"blocker: unhandled_exception {type(e).__name__}: {e}\n")
        return 2

    sys.stdout.write(f"{result.status}\n")
    if result.blockers:
        for b in result.blockers:
            sys.stdout.write(f"blocker: {b}\n")
    # High-signal details only (avoid noisy dumps).
    w = result.details.get("window") or {}
    sys.stdout.write(
        "window: "
        f"last_trading_day_ny={w.get('last_trading_day_ny')} "
        f"start_utc={w.get('start_utc')} "
        f"end_utc={w.get('end_utc')}\n"
    )
    sys.stdout.write(f"symbols: {', '.join(result.details.get('symbols') or [])}\n")
    ing = result.details.get("ingestion") or {}
    for sym, meta in ing.items():
        sys.stdout.write(f"ingestion: {sym} bars={meta.get('bars')}\n")
    st = result.details.get("strategy") or {}
    sys.stdout.write(
        f"strategy: signals_total={st.get('signals_total')} trade_signals_total={st.get('trade_signals_total')}\n"
    )
    if result.details.get("execution"):
        for r in result.details["execution"]:
            sys.stdout.write(
                f"execution: {r.get('symbol')} {r.get('side')} status={r.get('status')} "
                f"risk_allowed={r.get('risk_allowed')} risk_reason={r.get('risk_reason')}\n"
            )
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

