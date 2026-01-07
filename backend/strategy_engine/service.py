from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Response

from backend.common.agent_boot import configure_startup_logging
from backend.safety.config import load_kill_switch, load_stale_threshold_seconds
from backend.safety.safety_state import evaluate_safety_state, is_safe_to_run_strategies

from .driver import run_strategy, _fetch_marketdata_heartbeat, _parse_iso_dt

app = FastAPI(title="AgentTrader Strategy Engine")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _identity() -> dict[str, Any]:
    return {
        "agent_name": "strategy-engine",
        "workload": os.getenv("WORKLOAD") or None,
        "git_sha": os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        "environment": os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
    }


async def _current_state() -> tuple[str, dict[str, Any]]:
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

    status = "ok" if is_safe_to_run_strategies(state) else "halted"
    payload = {
        "status": status,
        "identity": _identity(),
        "safety_state": {
            "trading_enabled": state.trading_enabled,
            "kill_switch": state.kill_switch,
            "marketdata_fresh": state.marketdata_fresh,
            "marketdata_last_ts": state.marketdata_last_ts.isoformat() if state.marketdata_last_ts else None,
            "reason_codes": state.reason_codes,
            "updated_at": state.updated_at.isoformat(),
            "ttl_seconds": state.ttl_seconds,
            "stale_threshold_seconds": threshold,
        },
        "marketdata_heartbeat": hb,
    }
    return status, payload


@app.on_event("startup")
async def _startup() -> None:
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Serve strategy-engine health endpoints and run strategy cycles with fail-closed safety gating.",
    )

    # Background cycle loop (evaluation only; never enables execution).
    cycle_s = float(os.getenv("STRATEGY_CYCLE_SECONDS") or "30")
    cycle_s = max(5.0, min(cycle_s, 300.0))

    async def _loop() -> None:
        while True:
            try:
                # Never enable execution here (safety-first; EXECUTE is explicitly out-of-scope).
                await run_strategy(execute=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Best-effort: keep process alive; health endpoints reflect state via heartbeat.
                pass
            await asyncio.sleep(cycle_s)

    app.state.cycle_task = asyncio.create_task(_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    task: asyncio.Task | None = getattr(app.state, "cycle_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except Exception:
            pass


@app.get("/health")
async def health() -> dict[str, Any]:
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "ok", "service": "strategy-engine"}


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    status, payload = await _current_state()
    response.status_code = 200 if status == "ok" else 503
    return payload


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    status, payload = await _current_state()
    response.status_code = 200 if status == "ok" else 503
    return payload


@app.get("/livez")
async def livez() -> dict[str, Any]:
    return {"status": "alive", "identity": _identity()}

