import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import os
import json

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

from backend.common.marketdata_heartbeat import snapshot
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        # Never block startup for observability.
        pass
    print("Starting Alpaca streamer...")
    asyncio.create_task(alpaca_streamer_main())

@app.get("/")
async def read_root():
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer", **get_build_fingerprint()}


@app.get("/healthz")
async def healthz_check():
    # Alias for institutional conventions.
    return await health_check()

@app.get("/healthz")
async def healthz():
    """
    Heartbeat contract endpoint.

    Returns 200 only when marketdata ticks are fresh; otherwise returns 503.
    Consumers should treat any non-200 (or fetch error) as stale and refuse to run.
    """
    # Debug-only override to simulate staleness in lower envs.
    force_stale = os.getenv("MARKETDATA_FORCE_STALE", "").strip().lower() in {"1", "true", "yes", "on"}
    max_age = int(os.getenv("MARKETDATA_MAX_AGE_SECONDS", "60"))

    snap = snapshot()
    last_tick_epoch = snap.last_tick_epoch_seconds()

    now = datetime.now(timezone.utc).timestamp()
    age_seconds = None
    ok = False
    if last_tick_epoch is not None:
        age_seconds = float(now - float(last_tick_epoch))
        ok = age_seconds <= float(max_age)

    if force_stale:
        ok = False

    payload = {
        "service": "marketdata-mcp-server",
        "last_tick_epoch_seconds": last_tick_epoch,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age,
        "ok": ok,
        "forced_stale": force_stale,
    }
    if not ok:
        # 503 => not ready / stale
        return JSONResponse(payload, status_code=503)
    return JSONResponse(payload, status_code=200)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)