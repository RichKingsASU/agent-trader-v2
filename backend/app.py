import uvicorn
from fastapi import FastAPI
import asyncio
import sys
import os

from backend.common.agent_boot import configure_startup_logging
from backend.observability.correlation import install_fastapi_correlation_middleware
from backend.observability.logger import log_event

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
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)