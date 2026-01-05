from __future__ import annotations

import os
from functools import lru_cache
import json
import os
from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Runtime configuration.

    Notes:
    - On Cloud Run, prefer Workload Identity (ADC) for all GCP APIs.
    - GitHub credentials are fetched from Secret Manager by default.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Service identity
    APP_NAME: str = "mcp-github-gcp"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"

    # HTTP
    HOST: str = "0.0.0.0"
    PORT: int = 8080

    # Auth (Cloud Run IAM / Google-issued ID tokens)
    # - For local dev, set AUTH_DISABLED=true
    AUTH_DISABLED: bool = False
    # Comma-separated acceptable audiences (typically your Cloud Run service URL).
    AUTH_AUDIENCES: List[str] = Field(default_factory=list)
    # Optional allowlist; if non-empty, the token's email must be in the list.
    AUTH_ALLOWED_EMAILS: List[str] = Field(default_factory=list)

    # GCP defaults
    # Accept common env var names used by GCP tooling and Cursor MCP configs.
    GCP_PROJECT: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GCP_PROJECT", "PROJECT_ID", "GOOGLE_CLOUD_PROJECT"),
    )
    # Prefer the global endpoint for APIs that support it (e.g., Vertex AI).
    # Region-specific services can still override this via env var.
    GCP_LOCATION: str = Field(
        default="global",
        validation_alias=AliasChoices("GCP_LOCATION", "GOOGLE_CLOUD_LOCATION"),
    )

    # Optional explicit creds file (recommended only for local dev).
    # On GCP, prefer ADC / Workload Identity (no JSON key file).
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    # Vertex AI defaults (when used by MCP tools).
    # - Global endpoint: avoids region-pinned client config unless explicitly desired.
    VERTEX_AI_ENDPOINT: str = "https://aiplatform.googleapis.com"
    # Default model for all Vertex AI Gemini usage in this repo.
    VERTEX_AI_MODEL: str = "gemini-2.5-flash"

    @property
    def vertex_ai_discovery_url(self) -> str:
        """
        Stable Vertex AI v1 Gemini generateContent endpoint.

        Example:
        https://aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/publishers/google/models/gemini-2.5-flash:generateContent
        """
        project = self.GCP_PROJECT or "${PROJECT_ID}"
        endpoint = self.VERTEX_AI_ENDPOINT.rstrip("/")
        location = (self.GCP_LOCATION or "global").strip() or "global"
        model = (self.VERTEX_AI_MODEL or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        return (
            f"{endpoint}/v1/projects/{project}/locations/{location}"
            f"/publishers/google/models/{model}:generateContent"
        )

    def _validate_google_application_credentials(self) -> None:
        """
        If GOOGLE_APPLICATION_CREDENTIALS is set, ensure it's an absolute path
        to a valid JSON service account key.
        """
        path = self.GOOGLE_APPLICATION_CREDENTIALS
        if not path:
            return
        if not os.path.isabs(path):
            raise ValueError(f"GOOGLE_APPLICATION_CREDENTIALS must be an absolute path: {path}")
        if not os.path.isfile(path):
            raise ValueError(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"GOOGLE_APPLICATION_CREDENTIALS is not valid JSON: {path} ({e})") from e

        # Basic sanity checks for service account keys (don't over-validate).
        if not isinstance(data, dict) or not data.get("client_email") or not data.get("private_key"):
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS does not look like a service account key JSON "
                f"(missing client_email/private_key): {path}"
            )

    # GitHub auth options (priority order):
    # 1) GITHUB_TOKEN env var (local override)
    # 2) Secret Manager secret with an installation token / PAT (name in GITHUB_TOKEN_SECRET)
    # 3) GitHub App flow: app id + installation id + private key (values or Secret Manager names)
    GITHUB_API_BASE: str = "https://api.github.com"

    GITHUB_TOKEN: Optional[str] = None
    GITHUB_TOKEN_SECRET: Optional[str] = None

    GITHUB_APP_ID: Optional[str] = None
    GITHUB_INSTALLATION_ID: Optional[str] = None
    # PEM-encoded private key string (including BEGIN/END lines)
    GITHUB_PRIVATE_KEY_PEM: Optional[str] = None

    GITHUB_APP_ID_SECRET: Optional[str] = None
    GITHUB_INSTALLATION_ID_SECRET: Optional[str] = None
    GITHUB_PRIVATE_KEY_PEM_SECRET: Optional[str] = None

    # For Secret Manager reads when secret names are provided without project prefix
    GCP_SECRETS_PROJECT: Optional[str] = None

    def resolved_gcp_project(self) -> Optional[str]:
        """
        Resolve the active GCP project id.

        Priority:
        - VERTEX_AI_PROJECT_ID (explicit override)
        - FIREBASE_PROJECT_ID (repo standard)
        - GCP_PROJECT (this service's legacy field)
        - GOOGLE_CLOUD_PROJECT (ADC default)
        """
        return (
            self.VERTEX_AI_PROJECT_ID
            or self.FIREBASE_PROJECT_ID
            or self.GCP_PROJECT
            or self.GOOGLE_CLOUD_PROJECT
            or os.getenv("FIRESTORE_PROJECT_ID")  # back-compat with other services
        )

    def resolved_gcp_location(self) -> str:
        """
        Resolve the active GCP location/region.

        Priority:
        - VERTEX_AI_LOCATION (explicit override)
        - GCP_LOCATION (service default)
        """
        return self.VERTEX_AI_LOCATION or self.GCP_LOCATION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings._validate_google_application_credentials()
    return settings

