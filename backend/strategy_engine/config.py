from __future__ import annotations

from dataclasses import dataclass

from backend.common.config import env_csv, env_int, env_str
from backend.common.secrets import get_secret

@dataclass(frozen=True)
class Config:
    database_url: str
    strategy_name: str
    strategy_symbols: list[str]
    strategy_bar_lookback_minutes: int
    strategy_flow_lookback_minutes: int

    # Vertex AI (Gemini)
    # Keep a sane default so deployments don't need to set this explicitly.
    vertex_ai_model_id: str

_config: Config | None = None


def get_config() -> Config:
    """
    Load config at runtime (never at import time).
    """

    global _config
    if _config is not None:
        return _config

    cfg = Config(
        database_url=get_secret("DATABASE_URL", required=True),
        strategy_name=env_str("STRATEGY_NAME", default="naive_flow_trend") or "naive_flow_trend",
        strategy_symbols=env_csv("STRATEGY_SYMBOLS", default=["SPY", "IWM", "QQQ"]),
        strategy_bar_lookback_minutes=int(env_int("STRATEGY_BAR_LOOKBACK_MINUTES", default=30) or 30),
        strategy_flow_lookback_minutes=int(env_int("STRATEGY_FLOW_LOOKBACK_MINUTES", default=5) or 5),
        vertex_ai_model_id=env_str("VERTEX_AI_MODEL_ID", default="gemini-2.5-flash") or "gemini-2.5-flash",
    )
    _config = cfg
    return cfg