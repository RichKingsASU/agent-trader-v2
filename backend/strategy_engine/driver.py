import argparse
import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone

from backend.common.agent_boot import configure_startup_logging
from backend.common.freshness import check_freshness, stale_after_for_bar_interval
from backend.common.kill_switch import get_kill_switch_state
from backend.common.ops_http_server import OpsHttpServer
from backend.common.ops_log import log_json
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status
from backend.common.ops_metrics import (
    agent_start_total,
    errors_total,
    mark_activity,
    order_proposals_total,
    strategy_cycles_skipped_total,
    strategy_cycles_total,
)

from .config import config

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
    st = build_ops_status(
        service_name="strategy-engine",
        service_kind="strategy",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "strategy-engine"),
            agent_role=str(os.getenv("AGENT_ROLE") or "strategy"),
            agent_mode=str(os.getenv("AGENT_MODE") or "OBSERVE"),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(enabled),
        heartbeat_ttl_seconds=int(os.getenv("OPS_HEARTBEAT_TTL_S") or "60"),
        endpoints=EndpointsBlock(healthz="/healthz", heartbeat=None, metrics="/metrics"),
    )
    return st.model_dump()


async def run_strategy(execute: bool):
    """
    Main function to run the strategy engine (evaluation only).

    Safety contract:
    - No execution / no broker interaction (this service emits proposals only).
    - Refuse to evaluate when market data is stale (fail-closed NOOP).
    """
    # Global kill switch: halt strategy cycles immediately (no proposals emitted).
    # Note: execution agents also independently refuse broker-side actions, but this
    # prevents downstream load and makes "strategies halt" observable in ops logs.
    enabled, source = get_kill_switch_state()
    if enabled:
        try:
            log_json(
                intent_type="kill_switch_halt",
                severity="WARNING",
                reason_codes=["kill_switch"],
                message="Strategy engine halted by global kill switch; skipping cycle.",
                source=source,
                strategy=config.STRATEGY_NAME,
            )
        except Exception:
            pass
        return

    # This service is proposal-only. Keep `execute` for back-compat but do not act on it.
    _ = execute

    # Lazy import: avoid DB driver dependencies (asyncpg) when halted.
    from .models import fetch_recent_bars, fetch_recent_options_flow
    from .risk import can_place_trade, get_or_create_strategy_definition, log_decision
    from .strategies.naive_flow_trend import make_decision
    from backend.risk_allocator import RiskAllocator
    from backend.trading.agent_intent.emitter import emit_agent_intent
    from backend.trading.agent_intent.models import (
        AgentIntent,
        AgentIntentConstraints,
        AgentIntentRationale,
        IntentAssetType,
        IntentKind,
        IntentSide,
    )

    # Registry-backed identity in the risk/audit subsystem.
    strategy_id = await get_or_create_strategy_definition(config.STRATEGY_NAME)
    today = date.today()
    iteration_id = uuid.uuid4().hex
    allocator = RiskAllocator()

    try:
        log_json(intent_type="strategy_run_start", severity="INFO", strategy=config.STRATEGY_NAME, date=str(today), iteration_id=iteration_id)
    except Exception:
        pass

    # Data freshness policy: market_data_1m => 60s bars; stale if age > 2x interval.
    # Override via env if needed (seconds).
    bar_interval_s = int(os.getenv("MARKETDATA_BAR_INTERVAL_SECONDS") or "60")
    bar_interval_s = max(1, bar_interval_s)
    stale_after = stale_after_for_bar_interval(bar_interval=timedelta(seconds=bar_interval_s), multiplier=2.0)
    override = (os.getenv("MARKETDATA_STALE_AFTER_SECONDS") or "").strip()
    if override:
        try:
            stale_after = timedelta(seconds=max(0, int(override)))
        except Exception:
            # Keep default on bad input; fail-closed is enforced by the check itself.
            pass

    for symbol in config.STRATEGY_SYMBOLS:
        # A "cycle" is one symbol evaluation.
        strategy_cycles_total.inc(1.0)
        mark_activity("strategy-engine")
        global _last_cycle_at_iso
        _last_cycle_at_iso = _utc_now_iso()

        try:
            log_json(
                intent_type="strategy_symbol_start",
                severity="INFO",
                symbol=symbol,
                strategy=config.STRATEGY_NAME,
                iteration_id=iteration_id,
            )
        except Exception:
            pass

        try:
            bars = await fetch_recent_bars(symbol, config.STRATEGY_BAR_LOOKBACK_MINUTES)
            flow_events = await fetch_recent_options_flow(symbol, config.STRATEGY_FLOW_LOOKBACK_MINUTES)
        except Exception as e:
            # Skip this cycle on internal failures (SLO-aligned).
            strategy_cycles_skipped_total.inc(1.0)
            errors_total.inc(labels={"component": "strategy-engine"})
            try:
                log_json(
                    intent_type="strategy_cycle_skipped",
                    severity="ERROR",
                    reason_codes=["internal_error"],
                    error_type=type(e).__name__,
                    error=str(e),
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    iteration_id=iteration_id,
                )
            except Exception:
                pass
            continue

        # --- Per-strategy circuit breakers (safety-only; disabled unless configured) ---
        # Missing market data (objective, no market assumptions).
        md_missing = check_missing_market_data(bars=bars, source="bars:public.market_data_1m")
        if md_missing.triggered:
            strategy_cycles_skipped_total.inc(1.0)
            try:
                log_json(
                    intent_type="circuit_breaker_triggered",
                    severity="WARNING",
                    breaker_type="missing_market_data",
                    reason_codes=[md_missing.reason_code],
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    iteration_id=iteration_id,
                    details=md_missing.details,
                )
            except Exception:
                pass
            await log_decision(strategy_id, symbol, "flat", md_missing.message, {"reason_code": md_missing.reason_code}, False)
            continue

        # Abnormal volatility (ratio-based; threshold is operator-configured, default disabled).
        try:
            ratio_thr_raw = (os.getenv("STRATEGY_CB_VOL_RATIO_THRESHOLD") or "").strip()
            ratio_thr = float(ratio_thr_raw) if ratio_thr_raw else 0.0
        except Exception:
            ratio_thr = 0.0
        if ratio_thr > 0:
            vol_cb = check_abnormal_volatility(
                bars=bars,
                source="bars:public.market_data_1m",
                recent_n=int(os.getenv("STRATEGY_CB_VOL_RECENT_N") or "5"),
                baseline_n=int(os.getenv("STRATEGY_CB_VOL_BASELINE_N") or "30"),
                ratio_threshold=ratio_thr,
            )
            if vol_cb.triggered:
                strategy_cycles_skipped_total.inc(1.0)
                try:
                    log_json(
                        intent_type="circuit_breaker_triggered",
                        severity="WARNING",
                        breaker_type="abnormal_volatility",
                        reason_codes=[vol_cb.reason_code],
                        symbol=symbol,
                        strategy=config.STRATEGY_NAME,
                        iteration_id=iteration_id,
                        details=vol_cb.details,
                    )
                except Exception:
                    pass
                await log_decision(strategy_id, symbol, "flat", vol_cb.message, {"reason_code": vol_cb.reason_code}, False)
                continue

        # Freshness contract: refuse to evaluate if latest bar timestamp is stale.
        latest_bar_ts = bars[0].ts if bars else None
        freshness = check_freshness(
            latest_ts=latest_bar_ts,
            stale_after=stale_after,
            source="bars:public.market_data_1m",
        )
        if not freshness.ok:
            strategy_cycles_skipped_total.inc(1.0)
            try:
                log_json(
                    intent_type="STALE_DATA",
                    severity="WARNING",
                    reason_codes=["stale_data" if freshness.reason_code == "STALE_DATA" else "missing_timestamp"],
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    iteration_id=iteration_id,
                    latest_ts_utc=(freshness.latest_ts_utc.isoformat() if freshness.latest_ts_utc else None),
                    now_utc=freshness.now_utc.isoformat(),
                    age_seconds=(float(freshness.age.total_seconds()) if freshness.age is not None else None),
                    threshold_seconds=float(freshness.stale_after.total_seconds()),
                    source=freshness.details.get("source"),
                    assumed_utc=bool(freshness.details.get("assumed_utc", False)),
                )
            except Exception:
                pass

            reason = (
                f"STALE_DATA: source={freshness.details.get('source')} "
                f"age_s={freshness.details.get('age_seconds')} "
                f"threshold_s={freshness.details.get('threshold_seconds')}"
            )
            await log_decision(strategy_id, symbol, "flat", reason, {"reason_code": freshness.reason_code}, False)
            try:
                log_json(
                    intent_type="strategy_decision",
                    severity="INFO",
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    action="flat",
                    reason=reason,
                    iteration_id=iteration_id,
                )
            except Exception:
                pass
            continue

        decision = make_decision(bars, flow_events)
        action = decision.get("action")

        if action == "flat":
            await log_decision(strategy_id, symbol, "flat", decision["reason"], decision["signal_payload"], False)
            try:
                log_json(
                    intent_type="strategy_decision",
                    severity="INFO",
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    action="flat",
                    reason=decision.get("reason"),
                    iteration_id=iteration_id,
                )
            except Exception:
                pass
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
                    iteration_id=iteration_id,
                )
            except Exception:
                pass

        # Centralized decision flow:
        # - strategies emit intent only (no qty/notional)
        # - allocator sizes + applies capital-bearing gates (e.g., notional limits)
        created_at_utc = datetime.now(timezone.utc)
        side = (
            IntentSide.BUY
            if str(action).lower() == "buy"
            else IntentSide.SELL
            if str(action).lower() == "sell"
            else IntentSide.FLAT
        )
        intent = AgentIntent(
            created_at_utc=created_at_utc,
            repo_id=str(os.getenv("REPO_ID") or "unknown_repo"),
            agent_name=str(os.getenv("AGENT_NAME") or "strategy-engine"),
            strategy_name=config.STRATEGY_NAME,
            strategy_version=os.getenv("STRATEGY_VERSION") or None,
            correlation_id=iteration_id,
            symbol=symbol,
            asset_type=IntentAssetType.EQUITY,
            option=None,
            kind=IntentKind.DIRECTIONAL,
            side=side,
            confidence=None,
            rationale=AgentIntentRationale(
                short_reason=str(decision.get("reason") or "").strip() or "Strategy decision",
                indicators=decision.get("signal_payload") or {},
            ),
            constraints=AgentIntentConstraints(
                valid_until_utc=(
                    created_at_utc
                    + timedelta(
                        minutes=(
                            int(os.getenv("INTENT_TTL_MINUTES") or "5")
                            if str(os.getenv("INTENT_TTL_MINUTES") or "").strip().isdigit()
                            else 5
                        )
                    )
                ),
                requires_human_approval=True,
                order_type="market",
                time_in_force="day",
                limit_price=None,
                delta_to_hedge=None,
            ),
        )
        emit_agent_intent(intent)

        last_price = float(bars[0].close) if bars else 0.0
        allocation = await allocator.allocate_for_strategy_limits(
            intent=intent,
            strategy_id=strategy_id,
            trading_date=today,
            last_price=last_price,
            can_place_trade_fn=can_place_trade,
        )
        if not allocation.allowed:
            reason = "Risk limit exceeded."
            await log_decision(strategy_id, symbol, action, reason, decision.get("signal_payload") or {}, False)
            try:
                log_json(
                    intent_type="strategy_decision",
                    severity="WARNING",
                    symbol=symbol,
                    strategy=config.STRATEGY_NAME,
                    action=action,
                    reason=reason,
                    blocked=True,
                    block_reason="risk_limit",
                    iteration_id=iteration_id,
                )
            except Exception:
                pass
            continue

        # Proposal emitted only (no execution in this service).
        await log_decision(
            strategy_id,
            symbol,
            action,
            decision.get("reason") or "",
            decision.get("signal_payload") or {},
            False,
        )
        try:
            log_json(
                intent_type="strategy_decision",
                severity="INFO",
                symbol=symbol,
                strategy=config.STRATEGY_NAME,
                action=action,
                reason=decision.get("reason"),
                iteration_id=iteration_id,
            )
        except Exception:
            pass


if __name__ == "__main__":
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Run the strategy engine loop (fetch data, decide); enforce global kill-switch and stale-marketdata gating.",
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
        try:
            log_json(
                intent_type="ops_http_server_failed",
                severity="ERROR",
                service="strategy-engine",
                error_type=type(e).__name__,
                error=str(e),
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
    except Exception as e:
        errors_total.inc(labels={"component": "strategy-engine"})
        raise
    finally:
        try:
            srv.stop()
        except Exception:
            pass
