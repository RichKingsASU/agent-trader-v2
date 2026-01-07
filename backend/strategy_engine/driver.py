import asyncio
from datetime import date
import argparse
import os
from datetime import datetime, timezone

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state, require_live_mode
from backend.common.ops_http_server import OpsHttpServer
from backend.common.ops_log import log_json
from backend.common.ops_metrics import (
    agent_start_total,
    errors_total,
    mark_activity,
    order_proposals_total,
    safety_halted_total,
    strategy_cycles_skipped_total,
    strategy_cycles_total,
)

from .config import config
from .models import fetch_recent_bars, fetch_recent_options_flow
from .risk import (
    get_or_create_strategy_definition,
    can_place_trade,
    log_decision,
)
from .strategies.naive_flow_trend import make_decision

_last_cycle_at_iso: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload() -> dict[str, object]:
    enabled, source = get_kill_switch_state()
    age = None
    try:
        # "strategy-engine" activity is marked per symbol evaluation.
        from backend.common.ops_metrics import activity_age_seconds

        age = activity_age_seconds("strategy-engine")
    except Exception:
        age = None
    return {
        "kill_switch_enabled": bool(enabled),
        "kill_switch_source": source,
        "last_cycle_at": _last_cycle_at_iso,
        "last_cycle_age_seconds": age,
    }


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

    for symbol in config.STRATEGY_SYMBOLS:
        # A "cycle" is one symbol evaluation.
        strategy_cycles_total.inc(1.0)
        mark_activity("strategy-engine")
        global _last_cycle_at_iso
        _last_cycle_at_iso = _utc_now_iso()

        print(f"Processing symbol: {symbol}")

        try:
            bars = await fetch_recent_bars(symbol, config.STRATEGY_BAR_LOOKBACK_MINUTES)
            flow_events = await fetch_recent_options_flow(symbol, config.STRATEGY_FLOW_LOOKBACK_MINUTES)
        except Exception as e:
            # Skip this cycle on internal failures (SLO-aligned).
            strategy_cycles_skipped_total.inc(1.0)
            errors_total.inc(labels={"component": "strategy-engine"})
            print(f"  Cycle skipped due to error: {type(e).__name__}: {e}")
            try:
                log_json(
                    intent_type="strategy_cycle_skipped",
                    severity="ERROR",
                    reason_codes=["internal_error"],
                    error_type=type(e).__name__,
                    error=str(e),
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                )
            except Exception:
                pass
            continue

        decision = make_decision(bars, flow_events)
        action = decision.get("action")

        if action == "flat":
            await log_decision(strategy_id, symbol, "flat", decision["reason"], decision["signal_payload"], False)
            print(f"  Decision: flat. Reason: {decision['reason']}")
            continue
        else:
            # We proposed an order (even if later blocked by risk / kill switch).
            order_proposals_total.inc(1.0)
            try:
                log_json(
                    intent_type="order_proposal",
                    severity="INFO",
                    symbol=symbol,
                    action=action,
                    strategy=config.STRATEGY_NAME,
                    reason=decision.get("reason"),
                )
            except Exception:
                pass

        # Calculate notional
        last_price = bars[0].close if bars else 0
        notional = last_price * decision.get("size", 0)

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

        if execute:
            # Never execute if the global kill switch is active.
            try:
                require_live_mode(operation="paper trade execution")
            except Exception as e:
                safety_halted_total.inc(1.0)
                print(f"  Safety halt: refusing execution due to kill switch: {e}")
                await log_decision(
                    strategy_id,
                    symbol,
                    action,
                    f"Safety halt: {e}",
                    decision["signal_payload"],
                    False,
                )
                try:
                    log_json(
                        intent_type="safety_halt",
                        severity="WARNING",
                        reason_codes=["kill_switch_enabled"],
                        symbol=symbol,
                        action=action,
                        strategy=config.STRATEGY_NAME,
                        error=str(e),
                    )
                except Exception:
                    pass
                continue

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
    agent_start_total.inc(labels={"component": "strategy-engine"})

    # Expose /ops/status and /metrics on the same PORT contract as other services.
    # Note: this is intentionally tiny (stdlib) to keep the strategy runtime lean.
    port = int(os.getenv("PORT", "8080"))
    srv = OpsHttpServer(host="0.0.0.0", port=port, service_name="strategy-engine", status_fn=_status_payload)
    try:
        srv.start()
    except Exception as e:
        errors_total.inc(labels={"component": "strategy-engine"})
        print(f"[strategy-engine] ops_http_server_failed: {type(e).__name__}: {e}", flush=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Kept for compatibility; strategy-engine does not execute (proposals only).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_strategy(args.execute))
    except Exception as e:
        errors_total.inc(labels={"component": "strategy-engine"})
        raise
    finally:
        try:
            srv.stop()
        except Exception:
            pass
