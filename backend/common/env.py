from __future__ import annotations

import os
from typing import Any


def get_env(name: str, default: Any = None, *, required: bool = False) -> Any:
    """
    Read an environment variable.

    - If set (and non-empty), returns its value (string).
    - If not set, returns default.
    - If required=True and not set, raises RuntimeError.
    """
    v = os.getenv(name)
    if v is not None and v != "":
        return v
    if required:
        raise RuntimeError(f"Missing required env var: {name}")
    return default


def get_firebase_project_id(*, required: bool = False) -> str:
    """
    Resolve the Firebase/GCP project id.

    Preferred:
    - FIREBASE_PROJECT_ID

    Back-compat / fallbacks:
    - FIRESTORE_PROJECT_ID
    - GOOGLE_CLOUD_PROJECT (ADC default)
    """
    v = (
        get_env("FIREBASE_PROJECT_ID", default=None, required=False)
        or get_env("FIRESTORE_PROJECT_ID", default=None, required=False)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None, required=False)
    )
    if v:
        return str(v)
    if required:
        raise RuntimeError(
            "Missing required env var: FIREBASE_PROJECT_ID (or FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT)"
        )
    return ""


def get_vertex_ai_model_id(*, default: str = "gemini-2.5-flash") -> str:
    """
    Resolve the Vertex AI model id used for Gemini.
    """
    return str(get_env("VERTEX_AI_MODEL_ID", default=default, required=False))


def get_vertex_ai_project_id(*, required: bool = False) -> str:
    """
    Resolve the Vertex AI project id.

    Priority:
    - VERTEX_AI_PROJECT_ID (explicit override)
    - FIREBASE_PROJECT_ID (repo standard)
    - GOOGLE_CLOUD_PROJECT (ADC default)
    """
    v = (
        get_env("VERTEX_AI_PROJECT_ID", default=None, required=False)
        or get_env("FIREBASE_PROJECT_ID", default=None, required=False)
        or get_env("GOOGLE_CLOUD_PROJECT", default=None, required=False)
    )
    if v:
        return str(v)
    if required:
        raise RuntimeError(
            "Missing required env var: VERTEX_AI_PROJECT_ID (or FIREBASE_PROJECT_ID / GOOGLE_CLOUD_PROJECT)"
        )
    return ""


def get_vertex_ai_location(*, default: str = "us-central1") -> str:
    """
    Resolve the Vertex AI location/region.
    """
    return str(get_env("VERTEX_AI_LOCATION", default=default, required=False))


def get_alpaca_key_id(*, required: bool = True) -> str:
    """
    Returns the Alpaca API key.

    Env contract (preferred):
    - ALPACA_API_KEY

    Back-compat:
    - ALPACA_KEY_ID
    """
    v = get_env("ALPACA_API_KEY", default=None, required=False) or get_env(
        "ALPACA_KEY_ID", default=None, required=False
    )
    if v:
        return str(v)

    if required:
        raise RuntimeError("Missing required env var: ALPACA_API_KEY")
    return ""


def get_alpaca_api_key(*, required: bool = True) -> str:
    """
    Alias for get_alpaca_key_id(), for clarity in new code.
    """
    return get_alpaca_key_id(required=required)


def get_alpaca_secret_key(*, required: bool = True) -> str:
    """
    Returns ALPACA_SECRET_KEY.
    """
    v = get_env("ALPACA_SECRET_KEY", default=None, required=False)
    if v:
        return str(v)

    if required:
        raise RuntimeError("Missing required env var: ALPACA_SECRET_KEY")
    return ""

