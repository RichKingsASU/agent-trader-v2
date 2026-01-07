import asyncio
from datetime import date, datetime, timezone
from datetime import timedelta
import argparse
import json

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

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
    # Fail-safe: refuse to run if marketdata is stale/unreachable.
    try:
        await asyncio.to_thread(assert_marketdata_fresh)
    except MarketDataStaleError as e:
        print(f"[strategy_engine] Refusing to run: {e}")
        raise

    strategy_id = await get_or_create_strategy_definition(config.STRATEGY_NAME)
    today = date.today()
    correlation_id = os.getenv("CORRELATION_ID") or uuid4().hex
    repo_id = os.getenv("REPO_ID") or "RichKingsASU/agent-trader-v2"
    proposal_ttl_minutes = int(os.getenv("PROPOSAL_TTL_MINUTES") or "5")
    
    print(f"Running strategy '{config.STRATEGY_NAME}' for {today}...")
    emitted_any = False

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

        # Emit a non-executing, auditable proposal at the "would trade" decision point.
        side = ProposalSide.BUY if str(action).lower() == "buy" else ProposalSide.SELL
        created_at_utc = datetime.now(timezone.utc)
        proposal = OrderProposal(
            created_at_utc=created_at_utc,
            repo_id=repo_id,
            agent_name="strategy-engine",
            strategy_name=config.STRATEGY_NAME,
            strategy_version=os.getenv("STRATEGY_VERSION") or None,
            correlation_id=correlation_id,
            symbol=symbol,
            asset_type=ProposalAssetType.EQUITY,
            option=None,
            side=side,
            quantity=int(decision.get("size", 1) or 1),
            limit_price=None,
            rationale=ProposalRationale(
                short_reason=str(decision.get("reason") or "").strip() or "Strategy decision",
                indicators=decision.get("signal_payload", {}) or {},
            ),
            constraints=ProposalConstraints(
                valid_until_utc=(created_at_utc + timedelta(minutes=max(1, proposal_ttl_minutes))),
                requires_human_approval=True,
            ),
        )
        emit_proposal(proposal)
        emitted_any = True

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
            print("  Dry run mode, no trade executed.")
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
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass
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