import asyncio
import subprocess
from datetime import date
import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from backend.common.agent_boot import configure_startup_logging
from backend.safety.config import load_kill_switch, load_stale_threshold_seconds
from backend.safety.safety_state import evaluate_safety_state, is_safe_to_run_strategies

from .config import config
from .models import fetch_recent_bars, fetch_recent_options_flow
from .risk import (
    get_or_create_strategy_definition,
    get_or_create_today_state,
    can_place_trade,
    record_trade,
    log_decision,
)
from .strategies.naive_flow_trend import make_decision


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


async def _fetch_marketdata_heartbeat() -> dict[str, Any]:
    """
    Fetches the marketdata heartbeat from marketdata-mcp-server.
    Fail-closed: errors are surfaced via missing last_marketdata_ts.
    """
    url = str(os.getenv("MARKETDATA_HEARTBEAT_URL") or "http://marketdata-mcp-server/heartbeat").strip()
    timeout_s = float(os.getenv("MARKETDATA_HEARTBEAT_TIMEOUT_S") or "1.5")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            # Even if global kill-switch is enabled, heartbeat should be readable (200).
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return {"ok": resp.status_code == 200, "url": url, "status_code": resp.status_code, "data": data}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e), "data": {}}


def _log_intent(event: dict[str, Any]) -> None:
    try:
        print(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
    except Exception:
        # Best-effort, never crash strategy loop on logging.
        pass


async def run_strategy(execute: bool):
    """
    Main function to run the strategy engine.
    """
    # --- Preflight safety checks (fail-closed) ---
    kill = load_kill_switch()
    threshold = load_stale_threshold_seconds()
    hb = await _fetch_marketdata_heartbeat()
    last_ts = _parse_iso_dt((hb.get("data") or {}).get("last_marketdata_ts"))

    state = evaluate_safety_state(
        trading_enabled=True,
        kill_switch=kill,
        marketdata_last_ts=last_ts,
        stale_threshold_seconds=threshold,
        now=_utc_now(),
        ttl_seconds=30,
    )

    if not is_safe_to_run_strategies(state):
        _log_intent(
            {
                "ts": _utc_now().isoformat(),
                "intent_type": "strategy_cycle_skipped",
                "agent_name": "strategy-engine",
                "kill_switch": bool(kill),
                "stale_threshold_seconds": threshold,
                "marketdata_last_ts": last_ts.isoformat() if last_ts else None,
                "marketdata_heartbeat": hb,
                "reason_codes": list(state.reason_codes or []),
            }
        )
        return

    strategy_id = await get_or_create_strategy_definition(config.STRATEGY_NAME)
    today = date.today()
    
    print(f"Running strategy '{config.STRATEGY_NAME}' for {today}...")

    for symbol in config.STRATEGY_SYMBOLS:
        print(f"Processing symbol: {symbol}")

        bars = await fetch_recent_bars(symbol, config.STRATEGY_BAR_LOOKBACK_MINUTES)
        flow_events = await fetch_recent_options_flow(symbol, config.STRATEGY_FLOW_LOOKBACK_MINUTES)

        decision = make_decision(bars, flow_events)
        action = decision.get("action")

        if action == "flat":
            await log_decision(strategy_id, symbol, "flat", decision["reason"], decision["signal_payload"], False)
            print(f"  Decision: flat. Reason: {decision['reason']}")
            continue

        # Calculate notional
        last_price = bars[0].close if bars else 0
        notional = last_price * decision.get("size", 0)

        # Risk check
        if not await can_place_trade(strategy_id, today, notional):
            reason = "Risk limit exceeded."
            await log_decision(strategy_id, symbol, action, reason, decision["signal_payload"], False)
            print(f"  Decision: {action}, but trade blocked. Reason: {reason}")
            continue
            
        print(f"  Decision: {action}. Reason: {decision['reason']}")

        # Absolute safety: never execute unless explicitly in EXECUTE mode.
        agent_mode = str(os.getenv("AGENT_MODE") or "").strip().upper()
        execute_effective = bool(execute) and agent_mode == "EXECUTE"

        if execute_effective:
            print(f"  Executing {action} order for 1 {symbol}...")
            # Call the existing paper trade script
            process = subprocess.run(
                [
                    "python",
                    "backend/streams/manual_paper_trade.py",
                    symbol,
                    action,
                    str(decision.get("size", 1)),
                ],
                capture_output=True,
                text=True,
            )
            print(f"   manual_paper_trade.py stdout: {process.stdout}")
            print(f"   manual_paper_trade.py stderr: {process.stderr}")

            # Record the trade
            await record_trade(strategy_id, today, notional)
            await log_decision(
                strategy_id,
                symbol,
                action,
                decision["reason"],
                decision["signal_payload"],
                True,
            )
        else:
            print("  Dry run mode, no trade executed.")
            await log_decision(
                strategy_id,
                symbol,
                action,
                "Dry run mode.",
                decision["signal_payload"],
                False,
            )


if __name__ == "__main__":
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Run the strategy engine loop (fetch data, decide); enforce global kill-switch and stale-marketdata gating.",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually place paper trades.")
    args = parser.parse_args()

    asyncio.run(run_strategy(args.execute))