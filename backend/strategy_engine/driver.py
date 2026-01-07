import asyncio
from datetime import date
import argparse
import os
from uuid import uuid4

from backend.common.agent_boot import configure_startup_logging
from backend.trading.proposals.emitter import emit_proposal
from backend.trading.proposals.models import (
    OrderProposal,
    ProposalAssetType,
    ProposalConstraints,
    ProposalRationale,
    ProposalSide,
    ProposalOption,
    OptionRight,
)

from backend.common.agent_boot import configure_startup_logging
from backend.observability.correlation import bind_correlation_id
from backend.observability.logger import intent_start, intent_end, log_event

from .config import config
from .models import fetch_recent_bars, fetch_recent_options_flow
from .risk import (
    get_or_create_strategy_definition,
    can_place_trade,
    log_decision,
)
from .strategies.naive_flow_trend import make_decision

def _truthy_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


async def run_strategy(execute: bool):
    """
    Main function to run the strategy engine.
    """
    execute_requested = bool(execute)
    # Non-negotiable safety: never execute orders from this runtime.
    if execute:
        log_event(
            "execution_suppressed",
            level="WARNING",
            reason="Strategy runtime execution is disabled by policy (audit-trail only).",
        )
        execute = False

    strategy_id = await get_or_create_strategy_definition(config.STRATEGY_NAME)
    today = date.today()
    correlation_id = os.getenv("CORRELATION_ID") or uuid4().hex
    repo_id = os.getenv("REPO_ID") or "RichKingsASU/agent-trader-v2"
    proposal_ttl_minutes = int(os.getenv("PROPOSAL_TTL_MINUTES") or "5")
    
    print(f"Running strategy '{config.STRATEGY_NAME}' for {today}...")
    emitted_any = False

    cycle_ctx = intent_start(
        "strategy_evaluation_cycle",
        "Evaluate strategy signals for configured symbols.",
        payload={
            "strategy_name": config.STRATEGY_NAME,
            "strategy_id": strategy_id,
            "trade_date": str(today),
            "symbols": list(config.STRATEGY_SYMBOLS),
            "symbols_count": len(config.STRATEGY_SYMBOLS),
            "execute_requested": execute_requested,
            "execute_enabled": bool(execute),
        },
    )

    for symbol in config.STRATEGY_SYMBOLS:
        with bind_correlation_id():
            print(f"Processing symbol: {symbol}")

            bars = await fetch_recent_bars(symbol, config.STRATEGY_BAR_LOOKBACK_MINUTES)
            flow_events = await fetch_recent_options_flow(symbol, config.STRATEGY_FLOW_LOOKBACK_MINUTES)

            decision = make_decision(bars, flow_events)
            action = decision.get("action")

            sig_ctx = intent_start(
                "signal_produced",
                "Produced strategy signal (may be flat).",
                payload={
                    "strategy_name": config.STRATEGY_NAME,
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "action": action,
                    "reason": decision.get("reason"),
                    "signal_payload": decision.get("signal_payload") or {},
                },
            )
            intent_end(sig_ctx, "success")

            if action == "flat":
                await log_decision(strategy_id, symbol, "flat", decision["reason"], decision["signal_payload"], False)
                print(f"  Decision: flat. Reason: {decision['reason']}")
                continue

            # Calculate notional
            last_price = bars[0].close if bars else 0
            notional = last_price * decision.get("size", 0)

            # Risk check
            risk_allowed = await can_place_trade(strategy_id, today, notional)
            if not risk_allowed:
                reason = "Risk limit exceeded."
                proposal_ctx = intent_start(
                    "order_proposal",
                    "Would place order, but blocked by risk limits.",
                    payload={
                        "strategy_name": config.STRATEGY_NAME,
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "side": action,
                        "size": decision.get("size", 0),
                        "notional": notional,
                        "reason": reason,
                        "risk_allowed": False,
                        "would_execute": False,
                    },
                )
                intent_end(proposal_ctx, "success")

                await log_decision(strategy_id, symbol, action, reason, decision["signal_payload"], False)
                print(f"  Decision: {action}, but trade blocked. Reason: {reason}")
                continue
            
            print(f"  Decision: {action}. Reason: {decision['reason']}")

            # Intent point: order proposal (never executing).
            proposal_ctx = intent_start(
                "order_proposal",
                "Proposed order based on strategy decision (non-executing).",
                payload={
                    "strategy_name": config.STRATEGY_NAME,
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "side": action,
                    "size": decision.get("size", 1),
                    "notional": notional,
                    "reason": decision.get("reason"),
                    "risk_allowed": True,
                    "would_execute": False,
                },
            )
            intent_end(proposal_ctx, "success")

            print("  Dry run mode, no trade executed.")
            await log_decision(
                strategy_id,
                symbol,
                action,
                "Dry run mode.",
                decision["signal_payload"],
                False,
            )

    intent_end(cycle_ctx, "success")


if __name__ == "__main__":
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Run the strategy engine loop (fetch data, decide, and emit non-executing order proposals).",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Kept for compatibility; strategy-engine does not execute (proposals only).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_strategy(args.execute))
    except MarketDataStaleError:
        raise SystemExit(2)