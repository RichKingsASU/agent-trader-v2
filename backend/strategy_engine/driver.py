import asyncio
from datetime import date, datetime, timezone
from datetime import timedelta
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
    correlation_id = os.getenv("CORRELATION_ID") or uuid4().hex
    repo_id = os.getenv("REPO_ID") or "RichKingsASU/agent-trader-v2"
    proposal_ttl_minutes = int(os.getenv("PROPOSAL_TTL_MINUTES") or "5")
    
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

        if execute:
            # Intentionally non-executing: strategy-engine emits proposals only.
            print("  Execution is disabled in strategy-engine; proposal emitted only.")
            await log_decision(
                strategy_id,
                symbol,
                action,
                "Execution disabled; proposal emitted only.",
                decision["signal_payload"],
                False,
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

    # If no clear decision point is hit in a given environment, this provides a
    # safe way to validate formatting end-to-end without changing strategy math.
    if (not emitted_any) and _truthy_env("EMIT_DEMO_PROPOSAL", False):
        created_at_utc = datetime.now(timezone.utc)
        ttl = timedelta(minutes=max(1, proposal_ttl_minutes))
        for right in (OptionRight.CALL, OptionRight.PUT):
            demo = OrderProposal(
                created_at_utc=created_at_utc,
                repo_id=repo_id,
                agent_name="strategy-engine",
                strategy_name=f"{config.STRATEGY_NAME}-demo",
                strategy_version=os.getenv("STRATEGY_VERSION") or None,
                correlation_id=correlation_id,
                symbol="SPY",
                asset_type=ProposalAssetType.OPTION,
                option=ProposalOption(
                    expiration=(created_at_utc.date() + timedelta(days=7)),
                    right=right,
                    strike=500.0,
                    contract_symbol=None,
                ),
                side=ProposalSide.BUY,
                quantity=1,
                limit_price=1.23,
                rationale=ProposalRationale(
                    short_reason="Demo proposal (format verification only).",
                    indicators={"demo": True},
                ),
                constraints=ProposalConstraints(
                    valid_until_utc=(created_at_utc + ttl),
                    requires_human_approval=True,
                ),
            )
            emit_proposal(demo)


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