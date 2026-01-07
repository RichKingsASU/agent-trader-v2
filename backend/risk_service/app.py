from fastapi import FastAPI
from .routers import risk_limits

app = FastAPI(title="AgentTrader Risk Service")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

app.include_router(risk_limits.router)
