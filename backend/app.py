import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import os
import json

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status

from backend.common.marketdata_heartbeat import snapshot
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main

app = FastAPI()
install_fastapi_correlation_middleware(app)

@app.on_event("startup")
async def startup_event():
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    log_event("marketdata_streamer_starting")
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

def _query_last_tick_utc() -> datetime | None:
    """
    Best-effort: use the live_quotes table updated by the streamer.
    If unavailable, return None (status contract will treat as missing).
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return None
    try:
        import psycopg2  # local import to keep import-time safe

        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(last_update_ts) FROM public.live_quotes;")
                row = cur.fetchone()
                ts = row[0] if row else None
                if ts is None:
                    return None
                if isinstance(ts, datetime):
                    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
                return None
    except Exception:
        return None


@app.get("/ops/status")
async def ops_status() -> dict:
    kill, _source = get_kill_switch_state()
    stale_s = int(os.getenv("MARKETDATA_STALE_THRESHOLD_S") or "120")
    last_tick = _query_last_tick_utc()

    st = build_ops_status(
        service_name="marketdata-mcp-server",
        service_kind="marketdata",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "marketdata-mcp-server"),
            agent_role=str(os.getenv("AGENT_ROLE") or "marketdata"),
            agent_mode=str(os.getenv("AGENT_MODE") or "STREAM"),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("K_REVISION") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(kill),
        heartbeat_ttl_seconds=int(os.getenv("OPS_HEARTBEAT_TTL_S") or "60"),
        marketdata_last_tick_utc=last_tick,
        marketdata_stale_threshold_seconds=stale_s,
        endpoints=EndpointsBlock(healthz="/health", heartbeat=None, metrics=None),
    )
    return st.model_dump()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)