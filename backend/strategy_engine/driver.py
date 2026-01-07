import asyncio
import subprocess
from datetime import date
import argparse
import os

from backend.common.agent_boot import configure_startup_logging
from backend.strategies.registry.loader import load_config
from backend.strategies.registry.validator import compute_effective_mode
from backend.strategies.registry.models import StrategyMode

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

async def run_strategy(execute: bool):
    """
    Main function to run the strategy engine.
    """
    # Load strategy config from the repo-native registry (safe-by-default).
    # Back-compat: default strategy_id to STRATEGY_NAME.
    requested_id = (os.getenv("STRATEGY_ID") or config.STRATEGY_NAME).strip()
    cfg = load_config(requested_id)
    effective_mode = compute_effective_mode(cfg)

    if not cfg.enabled:
        print(f"Strategy '{cfg.strategy_id}' is disabled; exiting (safe-by-default).")
        return

    # Registry-backed identity in the risk/audit subsystem.
    strategy_id = await get_or_create_strategy_definition(cfg.strategy_id)
    today = date.today()
    
    print(
        f"Running strategy '{cfg.strategy_id}' for {today} "
        f"(requested_mode={cfg.mode.value} effective_mode={effective_mode.value})..."
    )

    bar_lookback = int(cfg.parameters.get("bar_lookback_minutes", config.STRATEGY_BAR_LOOKBACK_MINUTES))
    flow_lookback = int(cfg.parameters.get("flow_lookback_minutes", config.STRATEGY_FLOW_LOOKBACK_MINUTES))

    for symbol in cfg.symbols:
        print(f"Processing symbol: {symbol}")

        bars = await fetch_recent_bars(symbol, bar_lookback)
        flow_events = await fetch_recent_options_flow(symbol, flow_lookback)

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

        can_execute = bool(execute) and effective_mode == StrategyMode.EXECUTE
        if can_execute:
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
            print("  No execution (effective_mode is non-execute or --execute not set).")
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
        intent="Run the strategy engine loop (fetch data, decide, and optionally execute paper trades).",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually place paper trades.")
    args = parser.parse_args()

    try:
        asyncio.run(run_strategy(args.execute))
    except MarketDataStaleError:
        raise SystemExit(2)