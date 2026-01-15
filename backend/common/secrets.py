from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class SecretError(RuntimeError):
    pass


def _is_truthy(v: object | None) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_fallback_allowed() -> bool:
    """
    Controls whether secrets may be sourced from environment variables.

    Policy:
    - Default: DISALLOW (prevents accidental reliance on shell exports in prod).
    - Allow only when explicitly enabled via ALLOW_ENV_SECRET_FALLBACK=1.
    """
    return _is_truthy(os.getenv("ALLOW_ENV_SECRET_FALLBACK"))


def _get_nonempty_env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _resolve_project_id() -> str:
    """
    Resolve the GCP project id used for Secret Manager lookups.

    Priority order is intentionally broad to match mixed repo conventions.
    """
    for k in (
        "GCP_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
        "GCP_PROJECT_ID",
        "PROJECT_ID",
        "FIREBASE_PROJECT_ID",
        "FIRESTORE_PROJECT_ID",
    ):
        v = _get_nonempty_env(k)
        if v:
            return v
    raise SecretError(
        "Missing GCP project id for Secret Manager. "
        "Set one of: GCP_PROJECT, GOOGLE_CLOUD_PROJECT, GCLOUD_PROJECT, PROJECT_ID."
    )


def _secret_resource_name(name: str, *, project_id: Optional[str], version: str) -> str:
    n = str(name or "").strip()
    if not n:
        raise SecretError("Secret name is empty")

    # Full resource name already includes versions.
    if n.startswith("projects/") and "/secrets/" in n and "/versions/" in n:
        return n

    # Full secret name without versions.
    if n.startswith("projects/") and "/secrets/" in n:
        return f"{n}/versions/{version}"

    pid = (project_id or "").strip() or _resolve_project_id()
    return f"projects/{pid}/secrets/{n}/versions/{version}"


@lru_cache(maxsize=256)
def _access_secret_version(resource_name: str) -> str:
    """
    Access a Secret Manager secret version and return its decoded payload.

    Cached to avoid repeated Secret Manager calls in hot paths.
    """
    try:
        from google.cloud import secretmanager  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SecretError("google-cloud-secret-manager dependency is required") from e

    client = secretmanager.SecretManagerServiceClient()
    try:
        resp = client.access_secret_version(request={"name": resource_name})
    except Exception as e:
        raise SecretError(f"Failed to access secret: {resource_name} ({type(e).__name__}: {e})") from e

    data = getattr(getattr(resp, "payload", None), "data", None)  # bytes
    raw = (data or b"").decode("utf-8", errors="replace").strip()
    return raw


def get_secret(
    name: str,
    *,
    required: bool = True,
    version: str = "latest",
    project_id: Optional[str] = None,
    allow_env_fallback: bool = True,
) -> Optional[str]:
    """
    Retrieve a secret value.

    Sources:
    - Local fallback: environment variable (ONLY when ALLOW_ENV_SECRET_FALLBACK=1)
    - Primary: Google Secret Manager
      - If `name` is a full resource name (`projects/.../secrets/.../versions/...`), it is used directly.
      - Otherwise `name` is treated as the secret id within the resolved project.
    """
    if allow_env_fallback and _env_fallback_allowed():
        v = _get_nonempty_env(name)
        if v is not None:
            return v

    resource = _secret_resource_name(name, project_id=project_id, version=version)
    raw = _access_secret_version(resource)
    if raw:
        return raw
    if required:
        raise SecretError(f"Missing required secret: {resource}")
    return None


def get_database_url(*, required: bool = True, version: str = "latest", project_id: Optional[str] = None) -> str:
    """
    DATABASE_URL policy:
    - MUST be sourced from Secret Manager (no env fallback).
    """
    v = get_secret(
        "DATABASE_URL",
        required=required,
        version=version,
        project_id=project_id,
        allow_env_fallback=False,
    )
    if v is None:
        # Defensive; get_secret(required=True) raises above.
        raise SecretError("Missing required secret: DATABASE_URL")
    return str(v).strip()


def configure_database_url_env(*, version: str = "latest", project_id: Optional[str] = None) -> str:
    """
    Fetch DATABASE_URL from Secret Manager and set it in-process.

    This exists to preserve compatibility with modules that still validate
    env contracts at startup (expecting DATABASE_URL to be present).
    """
    url = get_database_url(required=True, version=version, project_id=project_id)
    os.environ["DATABASE_URL"] = url
    return url

