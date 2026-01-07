import uvicorn
from fastapi import FastAPI
import asyncio
import sys
import os
import json

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

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

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)