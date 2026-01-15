import os
from typing import Optional, Mapping
from google.api_core import exceptions
from google.cloud import secretmanager_v1

# Default project_id inference:
# We rely on GOOGLE_CLOUD_PROJECT or similar env vars to be available.
# If a secret itself contains the project ID, that's a more complex recursive problem.
# For now, assume project_id is available via common env vars.

_secret_manager_client = None

def _get_secret_manager_client() -> secretmanager_v1.SecretManagerServiceClient:
    """Initializes and returns the Secret Manager client."""
    global _secret_manager_client
    if _secret_manager_client is None:
        _secret_manager_client = secretmanager_v1.SecretManagerServiceClient()
    return _secret_manager_client


_allow_env_secret_fallback: Optional[bool] = None

def _should_allow_env_fallback() -> bool:
    """Checks if environment fallback for secrets is enabled globally."""
    global _allow_env_secret_fallback
    if _allow_env_secret_fallback is None:
        # ALLOW_ENV_SECRET_FALLBACK=1 enables fallback for non-DATABASE_URL secrets
        _allow_env_secret_fallback = os.getenv("ALLOW_ENV_SECRET_FALLBACK", "0").strip().lower() == "1"
    return _allow_env_secret_fallback


def get_secret(
    secret_name: str,
    project_id: Optional[str] = None,
    version: str = "latest",
    fail_if_missing: bool = True,
) -> str:
    """
    Retrieves a secret from Google Secret Manager.

    Args:
        secret_name: The name of the secret.
        project_id: The GCP project ID. If None, attempts to infer from environment
                    (e.g., GOOGLE_CLOUD_PROJECT, FIREBASE_PROJECT_ID).
        version: The secret version to access (e.g., 'latest', '1', '2').
        fail_if_missing: If True, raises an error if the secret is not found
                         and fallback is not possible/allowed. Defaults to True.

    Returns:
        The secret value as a string.

    Raises:
        RuntimeError: If the secret is not found and fail_if_missing is True,
                      or if project ID is missing and required.
        google.api_core.exceptions.NotFound: If the secret or version does not exist.
        google.api_core.exceptions.PermissionDenied: If permissions are insufficient.
    """
    # Environment fallback is globally gated and explicitly forbidden for DATABASE_URL.
    allow_env_fallback_for_this_secret = bool(_should_allow_env_fallback()) and (secret_name != "DATABASE_URL")

    # Infer project_id if not provided
    if not project_id:
        project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")

    if not project_id and fail_if_missing:
        raise RuntimeError(f"Project ID is required to retrieve secret '{secret_name}' and could not be inferred from environment.")

    secret_retrieved = False
    secret_value = ""
    error_message_sm = ""

    try:
        client = _get_secret_manager_client()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        secret_retrieved = True
    except exceptions.NotFound:
        error_message_sm = f"Secret '{secret_name}' (version: {version}) not found in project '{project_id}'."
    except exceptions.PermissionDenied:
        error_message_sm = f"Permission denied when accessing secret '{secret_name}' in project '{project_id}'. Ensure the service account has 'Secret Manager Accessor' role."
    except Exception as e:
        error_message_sm = f"An unexpected error occurred while accessing secret '{secret_name}': {e}"

    if secret_retrieved:
        return secret_value

    # If secret was not retrieved from Secret Manager
    if fail_if_missing:
        if allow_env_fallback_for_this_secret and secret_name != "DATABASE_URL":
            env_val = os.getenv(secret_name)
            if env_val is not None:
                print(f"Secret '{secret_name}' not found/accessible in Secret Manager, falling back to environment variable.")
                return str(env_val).strip()
            else:
                # Secret Manager failed, fallback to env failed too
                raise RuntimeError(f"{error_message_sm} Environment variable also not found.")
        else:
            # Fallback not allowed or not possible for this secret, or fail_if_missing is True.
            raise RuntimeError(f"{error_message_sm} Fallback to environment variable is not allowed/possible for this secret.")
    else:
        # fail_if_missing is False. Try fallback if allowed and possible.
        if allow_env_fallback_for_this_secret and secret_name != "DATABASE_URL":
            env_val = os.getenv(secret_name)
            if env_val is not None:
                print(f"Secret '{secret_name}' not found/accessible in Secret Manager, falling back to environment variable.")
                return str(env_val).strip()
        # If we reach here, secret not found/accessible, fail_if_missing is False,
        # and fallback didn't happen or wasn't allowed. Return empty string.
        return ""

# --- Functions for Alpaca Feeds ---
def get_alpaca_equities_feed(*, default: str = "iex") -> str:
    """
    Fetches the Alpaca equities feed name.
    Prioritizes ALPACA_EQUITIES_FEED secret.
    If not found, checks ALPACA_OPTIONS_FEED secret and uses it for equities feed
    (as per Task 1 requirement: "If only one feed secret exists: Treat it as ALPACA_EQUITIES_FEED").
    Falls back to the default 'iex' if no secret is found.
    """
    equities_secret = get_secret("ALPACA_EQUITIES_FEED", fail_if_missing=False)
    if equities_secret:
        return str(equities_secret).strip().lower()

    # If ALPACA_EQUITIES_FEED secret is missing, check for ALPACA_OPTIONS_FEED secret.
    options_secret = get_secret("ALPACA_OPTIONS_FEED", fail_if_missing=False)
    if options_secret:
        # Treat options feed as equities feed if it's the only one found.
        return str(options_secret).strip().lower()

    # If neither secret is found, use the provided default.
    return str(default).strip().lower()


def get_alpaca_options_feed(*, default: str | None = None) -> str | None:
    """
    Fetches the Alpaca options feed name from Secret Manager.
    Prioritizes ALPACA_OPTIONS_FEED secret.
    If only ALPACA_EQUITIES_FEED secret exists, it's treated as equities feed,
    so this function returns None in that case.
    If ALPACA_OPTIONS_FEED secret is missing, returns the provided default (or None).
    """
    options_secret = get_secret("ALPACA_OPTIONS_FEED", fail_if_missing=False)
    if options_secret:
        return str(options_secret).strip().lower()

    # If only ALPACA_EQUITIES_FEED secret exists, it's treated as equities feed.
    # This function should return None if the specific OPTIONS feed secret is not found.
    return default # Return None or explicit default if needed.

# --- Existing functions in secrets.py ---
# Keep existing functions like get_secret, etc.
# ... (rest of the existing secrets.py content) ...
