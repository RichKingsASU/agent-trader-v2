from fastapi import FastAPI
from .routers import risk_limits

app = FastAPI(title="AgentTrader Risk Service")

app.include_router(risk_limits.router)
