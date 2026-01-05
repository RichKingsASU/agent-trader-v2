import os

class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    STRATEGY_NAME = os.getenv("STRATEGY_NAME", "naive_flow_trend")
    STRATEGY_SYMBOLS = os.getenv("STRATEGY_SYMBOLS", "SPY,IWM,QQQ").split(",")
    STRATEGY_BAR_LOOKBACK_MINUTES = int(os.getenv("STRATEGY_BAR_LOOKBACK_MINUTES", "30"))
    STRATEGY_FLOW_LOOKBACK_MINUTES = int(os.getenv("STRATEGY_FLOW_LOOKBACK_MINUTES", "5"))

    # Vertex AI (Gemini)
    # Keep a sane default so deployments don't need to set this explicitly.
    VERTEX_AI_MODEL_ID = os.environ.get("VERTEX_AI_MODEL_ID", "gemini-2.5-flash")

config = Config()