from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.common.env import (
    get_vertex_ai_location,
    get_vertex_ai_model_id,
    get_vertex_ai_project_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VertexAIConfig:
    project_id: str
    location: str
    model_id: str

    @property
    def publisher_model_name(self) -> str:
        # Vertex publisher models are referenced by full resource name.
        return f"publishers/google/models/{self.model_id}"


def load_vertex_ai_config() -> VertexAIConfig:
    return VertexAIConfig(
        project_id=get_vertex_ai_project_id(required=False),
        location=get_vertex_ai_location(default="us-central1"),
        model_id=get_vertex_ai_model_id(default="gemini-2.5-flash"),
    )


def validate_vertex_model_or_log(cfg: VertexAIConfig) -> bool:
    """
    Best-effort validation that the configured publisher model exists.

    Important behavior:
    - If the model is missing (404), log a clear error and return False (no crash).
    - If credentials/permissions are missing, log and return False (no crash).
    - If the Vertex SDK is not installed, log and return False (no crash).
    """
    if not cfg.project_id:
        logger.warning(
            "Vertex AI not validated: missing project id. Set FIREBASE_PROJECT_ID (preferred) "
            "or VERTEX_AI_PROJECT_ID / GOOGLE_CLOUD_PROJECT."
        )
        return False

    try:
        from google.api_core.exceptions import NotFound, PermissionDenied  # type: ignore
        from google.api_core.client_options import ClientOptions  # type: ignore
        from google.cloud import aiplatform_v1beta1  # type: ignore
    except Exception as e:
        logger.warning(
            "Vertex AI not validated: Vertex SDK not available (%s). "
            "Install google-cloud-aiplatform to enable validation.",
            e,
        )
        return False

    try:
        # Use the regional Vertex endpoint so errors match runtime behavior.
        client = aiplatform_v1beta1.PublisherModelServiceClient(
            client_options=ClientOptions(api_endpoint=f"{cfg.location}-aiplatform.googleapis.com")
        )
        client.get_publisher_model(name=cfg.publisher_model_name)
        return True
    except NotFound:
        # This is the “404” case the repo was tripping over in some environments.
        logger.error(
            "Vertex AI model not found (404): %s. "
            "Update VERTEX_AI_MODEL_ID (recommended: gemini-2.5-flash) or ensure the model is available "
            "in this region/project. project_id=%s location=%s",
            cfg.publisher_model_name,
            cfg.project_id,
            cfg.location,
        )
        return False
    except PermissionDenied as e:
        logger.error(
            "Vertex AI validation failed (permission denied): %s. "
            "Ensure the runtime service account has Vertex AI permissions. project_id=%s location=%s model=%s",
            e,
            cfg.project_id,
            cfg.location,
            cfg.publisher_model_name,
        )
        return False
    except Exception as e:
        logger.exception(
            "Vertex AI validation failed (unexpected error): %s project_id=%s location=%s model=%s",
            e,
            cfg.project_id,
            cfg.location,
            cfg.publisher_model_name,
        )
        return False


def init_vertex_ai_or_log() -> bool:
    """
    Initialize Vertex AI and validate the configured model.

    This is intentionally non-fatal: it returns False and logs a clear error
    instead of crashing (notably on 404 / model not found).
    """
    cfg = load_vertex_ai_config()

    # Only attempt init if the SDK is present; validation function handles absence.
    try:
        import vertexai  # type: ignore
    except Exception:
        return validate_vertex_model_or_log(cfg)

    try:
        if cfg.project_id:
            vertexai.init(project=cfg.project_id, location=cfg.location)
        else:
            # Let ADC determine project; we still validate with clearer messaging above.
            vertexai.init(location=cfg.location)
    except Exception as e:
        logger.warning(
            "Vertex AI init failed (non-fatal): %s project_id=%s location=%s",
            e,
            cfg.project_id or "<adc>",
            cfg.location,
        )
        # Still attempt to validate model name for an actionable message.
        return validate_vertex_model_or_log(cfg)

    return validate_vertex_model_or_log(cfg)

