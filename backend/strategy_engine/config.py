from backend.common.config import env_csv, env_int, env_str

class Config:
    DATABASE_URL = env_str("DATABASE_URL")
    STRATEGY_NAME = env_str("STRATEGY_NAME", default="naive_flow_trend") or "naive_flow_trend"
    STRATEGY_SYMBOLS = env_csv("STRATEGY_SYMBOLS", default=["SPY", "IWM", "QQQ"])
    STRATEGY_BAR_LOOKBACK_MINUTES = int(env_int("STRATEGY_BAR_LOOKBACK_MINUTES", default=30) or 30)
    STRATEGY_FLOW_LOOKBACK_MINUTES = int(env_int("STRATEGY_FLOW_LOOKBACK_MINUTES", default=5) or 5)

    # Vertex AI (Gemini)
    # Keep a sane default so deployments don't need to set this explicitly.
    VERTEX_AI_MODEL_ID = env_str("VERTEX_AI_MODEL_ID", default="gemini-2.5-flash") or "gemini-2.5-flash"

config = Config()