from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from google.api_core import exceptions
from google.cloud import secretmanager_v1


@dataclass(frozen=True)
class SecretSpec:
    """
    Single contract for sensitive values.

    Notes:
    - Do not add alias env var names here. The contract is strict by design.
    - Secrets are resolved at runtime (never at import time).
    """

    purpose: str
    required: bool
    default: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical secret contract (authoritative)
# ---------------------------------------------------------------------------
SECRETS_CONTRACT: dict[str, SecretSpec] = {
    # Credentials / tokens
    "APCA_API_KEY_ID": SecretSpec(
        purpose="Alpaca API key id (trading + data auth).",
        required=True,
    ),
    "APCA_API_SECRET_KEY": SecretSpec(
        purpose="Alpaca API secret key (trading + data auth).",
        required=True,
    ),
    "EXEC_AGENT_ADMIN_KEY": SecretSpec(
        purpose="Optional auth key for execution-service admin endpoints (X-Exec-Agent-Key).",
        required=False,
        default="",
    ),
    "EXECUTION_CONFIRM_TOKEN": SecretSpec(
        purpose="Optional live-execution confirmation token (future/guardrail).",
        required=False,
        default="",
    ),
    "EXEC_IDEMPOTENCY_STORE_ID": SecretSpec(
        purpose="Optional idempotency store id (if using external idempotency store).",
        required=False,
        default="",
    ),
    "EXEC_IDEMPOTENCY_STORE_KEY": SecretSpec(
        purpose="Optional idempotency store auth key/secret (if using external idempotency store).",
        required=False,
        default="",
    ),
    "QUIVER_API_KEY": SecretSpec(
        purpose="Optional Quiver Quantitative API key for congressional disclosures ingest.",
        required=False,
        default="",
    ),
    "FRED_API_KEY": SecretSpec(
        purpose="Optional FRED API key for macro scraper enrichment.",
        required=False,
        default="",
    ),
    "NEWS_API_KEY": SecretSpec(
        purpose="Optional API key for news-ingest stub/client (NEWS_API_KEY).",
        required=False,
        default="",
    ),
    "OPTIONS_FLOW_API_KEY": SecretSpec(
        purpose="Optional API key for options flow stream source (stream-bridge).",
        required=False,
        default="",
    ),
    "NEWS_STREAM_API_KEY": SecretSpec(
        purpose="Optional API key for news stream source (stream-bridge).",
        required=False,
        default="",
    ),
    "ACCOUNT_UPDATES_API_KEY": SecretSpec(
        purpose="Optional API key for account updates stream source (stream-bridge).",
        required=False,
        default="",
    ),
    # Connection strings
    "DATABASE_URL": SecretSpec(
        purpose="Postgres connection string (includes credentials).",
        required=True,
    ),
    # Not strictly secret, but treated as a controlled credential-like input
    "APCA_API_BASE_URL": SecretSpec(
        purpose="Alpaca trading base URL (paper/live host selector).",
        required=False,
        default="https://paper-api.alpaca.markets",
    ),
    "ALPACA_DATA_HOST": SecretSpec(
        purpose="Optional Alpaca data host override (REST data base).",
        required=False,
        default="https://data.alpaca.markets",
    ),
    "ALPACA_DATA_FEED": SecretSpec(
        purpose="Optional Alpaca data feed selector (e.g. iex/sip).",
        required=False,
        default="iex",
    ),
    "ALPACA_DATA_STREAM_WS_URL": SecretSpec(
        purpose="Optional Alpaca data websocket URL override.",
        required=False,
        default="",
    ),
    "ALPACA_EQUITIES_FEED": SecretSpec(
        purpose="Optional equities feed selector (canonical; avoids ALPACA_FEED ambiguity).",
        required=False,
        default="iex",
    ),
    "ALPACA_OPTIONS_FEED": SecretSpec(
        purpose="Optional options feed selector (canonical; avoids ALPACA_FEED ambiguity).",
        required=False,
        default="",
    ),
}


_secret_manager_client: secretmanager_v1.SecretManagerServiceClient | None = None


def _get_secret_manager_client() -> secretmanager_v1.SecretManagerServiceClient:
    global _secret_manager_client
    if _secret_manager_client is None:
        _secret_manager_client = secretmanager_v1.SecretManagerServiceClient()
    return _secret_manager_client


def _infer_gcp_project_id() -> str | None:
    """
    Best-effort project id inference for Secret Manager lookups.
    These are runtime configuration values (not secrets).
    """

    return (
        (os.getenv("GCP_PROJECT") or "").strip()
        or (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
        or (os.getenv("FIREBASE_PROJECT_ID") or "").strip()
        or None
    )


def _invalid_secret_name_error(secret_name: str) -> ValueError:
    allowed = ", ".join(sorted(SECRETS_CONTRACT.keys()))
    return ValueError(
        "Invalid secret name "
        f"{secret_name!r}. Allowed secrets are: {allowed}. "
        "If you intended to read non-secret runtime configuration, use os.getenv()/os.environ "
        "or a dedicated env helper (and do not route it through backend.common.secrets)."
    )


def get_secret(
    secret_name: str,
    *,
    default: Optional[str] = None,
    project_id: Optional[str] = None,
    version: str = "latest",
    required: Optional[bool] = None,
    fail_if_missing: Optional[bool] = None,
) -> str:
    """
    Resolve a secret by canonical name (strict contract).

    Resolution order:
    - Environment variable with the same name (useful for local/CI)
    - Google Secret Manager (projects/<project_id>/secrets/<name>)

    Contract rules:
    - Secret name must be declared in SECRETS_CONTRACT (invalid names hard-fail).
    - Missing REQUIRED secrets hard-fail with an explicit message.
    - No alias env var names are supported.
    """

    if secret_name not in SECRETS_CONTRACT:
        raise _invalid_secret_name_error(secret_name)

    spec = SECRETS_CONTRACT[secret_name]

    # Back-compat: callers historically used fail_if_missing; treat it as the required flag.
    if fail_if_missing is not None:
        required_final = bool(fail_if_missing)
    elif required is not None:
        required_final = bool(required)
    else:
        required_final = bool(spec.required)

    default_final: Optional[str]
    if default is not None:
        default_final = default
    else:
        default_final = spec.default

    # 1) Env var (same name only).
    env_val = os.environ.get(secret_name)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip()

    # 2) Secret Manager.
    pid = (project_id or "").strip() or _infer_gcp_project_id()
    if pid:
        try:
            client = _get_secret_manager_client()
            sm_name = f"projects/{pid}/secrets/{secret_name}/versions/{version}"
            response = client.access_secret_version(request={"name": sm_name})
            return response.payload.data.decode("UTF-8").strip()
        except exceptions.NotFound:
            # fall through to missing/default handling
            pass
        except exceptions.PermissionDenied as e:
            raise RuntimeError(
                f"Permission denied when accessing secret {secret_name!r} in project {pid!r}. "
                "Ensure the runtime service account has 'Secret Manager Secret Accessor'."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Unexpected error while accessing secret {secret_name!r} from Secret Manager: {e}"
            ) from e

    # Missing / default handling.
    if not required_final:
        return str(default_final or "")

    project_hint = f"projects/{pid}/secrets/{secret_name}" if pid else f"<your-project>/secrets/{secret_name}"
    raise RuntimeError(
        f"Missing required secret {secret_name!r}. "
        f"Set env var {secret_name} or create Secret Manager secret {project_hint}."
    )


# ---------------------------------------------------------------------------
# Convenience helpers (still validated by the strict contract above)
# ---------------------------------------------------------------------------
def get_alpaca_equities_feed(*, default: str = "iex") -> str:
    v = str(get_secret("ALPACA_EQUITIES_FEED", required=False, default=default) or "").strip().lower()
    if v:
        return v
    # If only one feed is configured and it's OPTIONS, treat it as EQUITIES.
    v2 = str(get_secret("ALPACA_OPTIONS_FEED", required=False, default="") or "").strip().lower()
    return v2 or str(default).strip().lower()


def get_alpaca_options_feed(*, default: str | None = None) -> str | None:
    v = str(get_secret("ALPACA_OPTIONS_FEED", required=False, default="") or "").strip().lower()
    if v:
        return v
    return default
