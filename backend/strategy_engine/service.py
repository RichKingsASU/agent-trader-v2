from __future__ import annotations

from backend.common.config_contract import validate_or_exit as _validate_or_exit

# Fail-fast env contract validation (must run before other backend imports).
_validate_or_exit("strategy-engine")

from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_enforce_agent_mode_guard()

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import FastAPI, Response

from backend.common.agent_boot import configure_startup_logging
from backend.observability.ops_json_logger import OpsLogger

from .driver import run_strategy

app = FastAPI(title="AgentTrader Strategy Engine")
install_app_heartbeat(app, service_name="strategy-engine")


def _identity() -> dict[str, Any]:
    return {
        "agent_name": "strategy-engine",
        "workload": os.getenv("WORKLOAD") or None,
        "git_sha": os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        "environment": os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
    }


def _marketdata_heartbeat_url() -> str:
    """
    Prefer the explicit heartbeat URL (ops endpoint), else fall back to the
    standardized health URL.
    """
    v = (os.getenv("MARKETDATA_HEARTBEAT_URL") or "").strip()
    if v:
        return v
    v = (os.getenv("MARKETDATA_HEALTH_URL") or "").strip()
    if v:
        return v
    # Local default (dev).
    return "http://127.0.0.1:8080/heartbeat"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(str(raw).strip())


def _fetch_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        out = json.loads(body or "{}")
    except Exception:
        out = {"_raw": body[:2000]}
    return out if isinstance(out, dict) else {"payload": out}


async def _current_state() -> tuple[str, dict[str, Any]]:
    """
    Best-effort dependency snapshot used by /readyz.

    "ok" means the service can successfully fetch and parse marketdata heartbeat.
    We do NOT require marketdata to be "fresh" here; that gating belongs to the
    strategy execution path (fail-closed).
    """
    timeout_s = _env_float("MARKETDATA_HEALTH_TIMEOUT_SECONDS", 2.0)
    url = _marketdata_heartbeat_url()
    try:
        payload = await asyncio.to_thread(_fetch_json, url, timeout_s=timeout_s)
        return "ok", {
            "status": "ok",
            "identity": _identity(),
            "marketdata_heartbeat_url": url,
            "marketdata": payload,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return "marketdata_unreachable", {
            "status": "degraded",
            "identity": _identity(),
            "marketdata_heartbeat_url": url,
            "error": f"{type(e).__name__}: {e}",
        }


@app.on_event("startup")
async def _startup() -> None:
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="strategy-engine",
        intent="Serve strategy-engine health endpoints and run strategy cycles with fail-closed safety gating.",
    )

    app.state.ops_logger = OpsLogger("strategy-engine")
    app.state.shutting_down = False
    app.state.ready = False
    app.state.ready_logged = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        last_ops_log = 0.0
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            now = time.monotonic()
            if (now - last_ops_log) >= float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S") or "60"):
                last_ops_log = now
                try:
                    app.state.ops_logger.heartbeat(kind="loop")  # type: ignore[attr-defined]
                except Exception:
                    pass
            await asyncio.sleep(1.0)

    async def _initialize_readiness() -> None:
        """
        Flip readiness only after full dependency init.

        For this service, "ready" is defined as being able to evaluate the
        safety gate successfully at least once (including a marketdata
        heartbeat fetch).
        """
        while not getattr(app.state, "shutting_down", False):
            try:
                status, _payload = await _current_state()
                if status == "ok":
                    if not bool(getattr(app.state, "ready", False)):
                        app.state.ready = True
                    if not bool(getattr(app.state, "ready_logged", False)):
                        app.state.ready_logged = True
                        try:
                            app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    return
            except Exception:
                # Keep retrying; readiness endpoint already reflects state.
                pass
            await asyncio.sleep(2.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())
    app.state.init_task = asyncio.create_task(_initialize_readiness())

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

    # Readiness: startup completed and critical in-process loops scheduled.
    app.state.is_ready = True
    if not bool(getattr(app.state, "ready_logged", False)):
        app.state.ready_logged = True
        try:
            app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
        except Exception:
            pass


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.shutting_down = True
    app.state.ready = False
    try:
        app.state.ops_logger.shutdown(phase="initiated")  # type: ignore[attr-defined]
    except Exception:
        pass

    cycle_task: asyncio.Task | None = getattr(app.state, "cycle_task", None)
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)
    init_task: asyncio.Task | None = getattr(app.state, "init_task", None)

    for t in (cycle_task, loop_task, init_task):
        if t is None:
            continue
        try:
            t.cancel()
        except Exception:
            pass

    tasks = [t for t in (cycle_task, loop_task, init_task) if t is not None]
    if not tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10.0)
    except Exception:
        # Best-effort; never hang shutdown.
        pass


@app.get("/health")
async def health() -> dict[str, Any]:
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "ok", "service": "strategy-engine"}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive (do not gate on external dependencies).
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    if not ready:
        response.status_code = 503
        return {"status": "not_ready", "identity": _identity()}
    status, payload = await _current_state()
    response.status_code = 200 if status == "ok" else 503
    payload["ready"] = True
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
    return {"status": "ok" if ok else ("cycle_dead" if not cycle_ok else "wedged")}

