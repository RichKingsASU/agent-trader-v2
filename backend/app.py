import uvicorn
from fastapi import FastAPI
import asyncio
import sys
import os


from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main

app = FastAPI()

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