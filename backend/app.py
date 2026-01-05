import uvicorn
from fastapi import FastAPI
import asyncio
import sys
import os


from agenttrader.backend.streams.alpaca_streamer import main as alpaca_streamer_main

app = FastAPI()

# API routers (non-streaming endpoints)
try:
    from agenttrader.backend.routers.trades import router as trades_router

    app.include_router(trades_router)
except Exception as e:  # pragma: no cover
    # Keep streamer service booting even if DB/router deps are unavailable.
    print(f"[backend.app] trades router disabled: {e}")

@app.on_event("startup")
async def startup_event():
    print("Starting Alpaca streamer...")
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