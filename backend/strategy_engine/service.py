from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Response

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
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
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Serve strategy-engine health endpoints and run strategy cycles with fail-closed safety gating.",
    )

    app.state.shutting_down = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            await asyncio.sleep(1.0)

    async def _ready_log_once() -> None:
        """
        Emit a single high-signal log line once /readyz would return 200.
        """
        while not getattr(app.state, "shutting_down", False):
            try:
                status, _payload = await _current_state()
                if status == "ok":
                    print("SERVICE_READY: strategy-engine", flush=True)
                    return
            except Exception:
                # Keep retrying; readiness endpoint already reflects state.
                pass
            await asyncio.sleep(2.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())
    app.state.ready_log_task = asyncio.create_task(_ready_log_once())

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
    app.state.shutting_down = True
    try:
        print("shutdown_intent service=strategy-engine", flush=True)
    except Exception:
        pass

    cycle_task: asyncio.Task | None = getattr(app.state, "cycle_task", None)
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)
    ready_log_task: asyncio.Task | None = getattr(app.state, "ready_log_task", None)

    for t in (cycle_task, loop_task, ready_log_task):
        if t is None:
            continue
        try:
            t.cancel()
        except Exception:
            pass

    for t in (cycle_task, loop_task, ready_log_task):
        if t is None:
            continue
        try:
            await t
        except Exception:
            pass


@app.get("/health")
async def health() -> dict[str, Any]:
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "ok", "service": "strategy-engine"}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive (do not gate on external dependencies).
    return {"status": "ok", "identity": _identity()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    status, payload = await _current_state()
    response.status_code = 200 if status == "ok" else 503
    return payload


@app.get("/livez")
async def livez(response: Response) -> dict[str, Any]:
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "5")
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    loop_ok = (now - last) <= max_age_s
    cycle_task: asyncio.Task | None = getattr(app.state, "cycle_task", None)
    cycle_ok = cycle_task is not None and (not cycle_task.done())
    ok = loop_ok and cycle_ok and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {
        "status": "alive" if ok else ("cycle_dead" if not cycle_ok else "wedged"),
        "identity": _identity(),
        "loop_heartbeat_age_s": max(0.0, now - last),
        "max_age_s": max_age_s,
        "cycle_task_alive": bool(cycle_ok),
    }

