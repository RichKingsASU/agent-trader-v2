import os
from dataclasses import dataclass

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
    return Config(
        firestore_project_id=os.environ.get("FIRESTORE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        vertex_ai_model_id=os.environ.get("VERTEX_AI_MODEL_ID", "gemini-2.5-flash"),
        vertex_ai_project_id=os.environ.get("VERTEX_AI_PROJECT_ID") or os.environ.get("FIREBASE_PROJECT_ID"),
        vertex_ai_location=os.environ.get("VERTEX_AI_LOCATION", "us-central1"),
        price_stream_url=os.environ.get("PRICE_STREAM_URL"),
        options_flow_url=os.environ.get("OPTIONS_FLOW_URL"),
        options_flow_api_key=os.environ.get("OPTIONS_FLOW_API_KEY"),
        news_stream_url=os.environ.get("NEWS_STREAM_URL"),
        news_stream_api_key=os.environ.get("NEWS_STREAM_API_KEY"),
        account_updates_url=os.environ.get("ACCOUNT_UPDATES_URL"),
        account_updates_api_key=os.environ.get("ACCOUNT_UPDATES_API_KEY"),
    )
