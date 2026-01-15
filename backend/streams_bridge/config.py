from dataclasses import dataclass

from backend.common.config import env_str
from backend.common.secrets import get_secret

@dataclass
class Config:
    firestore_project_id: str | None
    vertex_ai_model_id: str | None
    vertex_ai_project_id: str | None
    vertex_ai_location: str | None
    price_stream_url: str | None
    options_flow_url: str | None
    options_flow_api_key: str | None
    news_stream_url: str | None
    news_stream_api_key: str | None
    account_updates_url: str | None
    account_updates_api_key: str | None

def load_config() -> Config:
    def _opt_secret(name: str) -> str | None:
        v = str(get_secret(name, required=False, default="") or "").strip()
        return v or None

    return Config(
        firestore_project_id=env_str("FIRESTORE_PROJECT_ID") or env_str("GOOGLE_CLOUD_PROJECT"),
        vertex_ai_model_id=env_str("VERTEX_AI_MODEL_ID", default="gemini-2.5-flash") or "gemini-2.5-flash",
        vertex_ai_project_id=env_str("VERTEX_AI_PROJECT_ID") or env_str("FIREBASE_PROJECT_ID"),
        vertex_ai_location=env_str("VERTEX_AI_LOCATION", default="us-central1") or "us-central1",
        price_stream_url=env_str("PRICE_STREAM_URL"),
        options_flow_url=env_str("OPTIONS_FLOW_URL"),
        options_flow_api_key=_opt_secret("OPTIONS_FLOW_API_KEY"),
        news_stream_url=env_str("NEWS_STREAM_URL"),
        news_stream_api_key=_opt_secret("NEWS_STREAM_API_KEY"),
        account_updates_url=env_str("ACCOUNT_UPDATES_URL"),
        account_updates_api_key=_opt_secret("ACCOUNT_UPDATES_API_KEY"),
    )
