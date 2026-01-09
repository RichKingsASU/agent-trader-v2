"""
Central config system (env parsing + validation).

Goals:
- Centralize env var parsing with required/optional sets.
- Fail fast at startup with single-line, actionable errors.
- Provide safe defaults where reasonable (do not "default" secrets).

Entry points should call validate_or_exit(service_name) as early as possible
to ensure misconfiguration crashes the container immediately.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# A requirement can be either:
# - "ENV_VAR_NAME" (must be present and non-empty)
# - ("ENV_A", "ENV_B", ...) (at least one must be present and non-empty)
EnvRequirement = str | Sequence[str]


class ConfigError(RuntimeError):
    """
    Raised when configuration is invalid.

    Important: the message must be a single line (no newlines) so container
    logs are one-line actionable.
    """

    def __init__(self, message: str) -> None:
        msg = " ".join(str(message).splitlines()).strip()
        super().__init__(msg)


def _get(env: Mapping[str, str], name: str) -> str | None:
    v = env.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _format_requirement(req: EnvRequirement) -> str:
    if isinstance(req, str):
        return req
    parts = [str(x).strip() for x in req if str(x).strip()]
    return "|".join(parts) if parts else "<invalid>"


def _normalize_aliases(*, env: Mapping[str, str] | None = None, aliases: dict[str, list[str]] | None = None) -> None:
    """
    Ensure canonical env var names are present by copying from first present alias.

    This never logs values (secrets-safe).
    """
    if not aliases:
        return
    e = os.environ if env is None else env
    # Only works for mutable envs (os.environ). If a mapping is supplied, skip.
    if e is not os.environ:
        return
    for target, alts in aliases.items():
        if _get(os.environ, target) is not None:
            continue
        for a in alts:
            v = _get(os.environ, a)
            if v is not None:
                os.environ[target] = v
                break


@dataclass(frozen=True)
class EnvContract:
    service: str
    required: list[EnvRequirement]
    optional: list[str]
    aliases: dict[str, list[str]]

    def validate(self, *, env: Mapping[str, str] | None = None) -> None:
        e: Mapping[str, str] = env or os.environ  # type: ignore[assignment]
        _normalize_aliases(env=env, aliases=self.aliases)

        missing: list[str] = []
        for req in self.required:
            if isinstance(req, str):
                if _get(e, req) is None:
                    missing.append(req)
                continue
            group = [str(x).strip() for x in req if str(x).strip()]
            if not group:
                missing.append("<invalid>")
                continue
            if all(_get(e, n) is None for n in group):
                missing.append(_format_requirement(group))

        if missing:
            raise ConfigError(
                "CONFIG_FAIL "
                f"service={self.service} "
                f"missing={','.join(missing)} "
                'action="Set missing env vars (Cloud Run: --set-env-vars/--set-secrets). '
                'See docs/DEPLOY_GCP.md#secrets-recommended-secret-manager and docs/CONFIG_SECRETS.md"'
            )


# --- Central contract registry (required/optional sets) ---
#
# Keep required focused on values needed for clean startup.
#
_COMMON_PROJECT_ALIASES = ["GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GCP_PROJECT_ID", "PROJECT_ID", "PUBSUB_PROJECT_ID"]

CONTRACTS: dict[str, EnvContract] = {
    # Existing services from legacy config_contract.py.
    "marketdata-mcp-server": EnvContract(
        service="marketdata-mcp-server",
        required=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "DATABASE_URL"],
        optional=["LOG_LEVEL", "ENV", "AGENT_MODE"],
        aliases={},
    ),
    "strategy-engine": EnvContract(
        service="strategy-engine",
        required=["DATABASE_URL", ("MARKETDATA_HEALTH_URL", "MARKETDATA_HEARTBEAT_URL")],
        optional=[
            "VERTEX_AI_MODEL_ID",
            "VERTEX_AI_PROJECT_ID",
            "VERTEX_AI_LOCATION",
            "ENV",
            "AGENT_MODE",
            "LOG_LEVEL",
        ],
        aliases={},
    ),
    # Cloud Run ingestion worker (topics + flag secret).
    "cloudrun-ingestor": EnvContract(
        service="cloudrun-ingestor",
        required=[
            # Canonical project id env name used by this service.
            "GCP_PROJECT",
            "SYSTEM_EVENTS_TOPIC",
            "MARKET_TICKS_TOPIC",
            "MARKET_BARS_1M_TOPIC",
            "TRADE_SIGNALS_TOPIC",
            "INGEST_FLAG_SECRET_ID",
        ],
        optional=["ENV", "LOG_LEVEL", "HEARTBEAT_INTERVAL_SECONDS", "FLAG_CHECK_INTERVAL_SECONDS"],
        aliases={"GCP_PROJECT": list(_COMMON_PROJECT_ALIASES) + ["GCP_PROJECT"]},
    ),
    # Cloud Run Pub/Sub -> Firestore materializer.
    "cloudrun-consumer": EnvContract(
        service="cloudrun-consumer",
        required=[
            "GCP_PROJECT",
            "SYSTEM_EVENTS_TOPIC",
            "INGEST_FLAG_SECRET_ID",
            "ENV",
        ],
        optional=[
            "LOG_LEVEL",
            "FIRESTORE_DATABASE",
            "FIRESTORE_COLLECTION_PREFIX",
            "DEFAULT_REGION",
            "SUBSCRIPTION_TOPIC_MAP",
            "DLQ_SAMPLE_RATE",
            "DLQ_SAMPLE_TTL_HOURS",
        ],
        aliases={"GCP_PROJECT": list(_COMMON_PROJECT_ALIASES) + ["GCP_PROJECT"]},
    ),
    # Stream bridge (Firestore project required; upstream stream URLs are optional).
    "stream-bridge": EnvContract(
        service="stream-bridge",
        required=[("FIREBASE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")],
        optional=[
            "DRY_RUN",
            "PRICE_STREAM_URL",
            "OPTIONS_FLOW_URL",
            "OPTIONS_FLOW_API_KEY",
            "NEWS_STREAM_URL",
            "NEWS_STREAM_API_KEY",
            "ACCOUNT_UPDATES_URL",
            "ACCOUNT_UPDATES_API_KEY",
        ],
        aliases={},
    ),
}


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Validate env var contract for the given service.

    On failure:
    - prints a single line beginning with "CONFIG_FAIL"
    - exits with code 1
    """
    key = (service or "").strip()
    contract = CONTRACTS.get(key)
    if contract is None:
        return
    try:
        contract.validate(env=env)
    except ConfigError as e:
        try:
            sys.stdout.write(str(e) + "\n")
            try:
                sys.stdout.flush()
            except Exception:
                pass
        except Exception:
            pass
        raise SystemExit(1)


# --- Typed env parsing helpers (use in config modules) ---
def env_str(name: str, *, default: str | None = None, required: bool = False, env: Mapping[str, str] | None = None) -> str | None:
    e = env or os.environ  # type: ignore[assignment]
    v = _get(e, name)
    if v is not None:
        return v
    if required:
        raise ConfigError(f"CONFIG_FAIL missing={name} action=\"Set {name} via env or Secret Manager\"")
    return default


def env_int(name: str, *, default: int | None = None, required: bool = False, env: Mapping[str, str] | None = None) -> int | None:
    raw = env_str(name, default=None, required=required, env=env)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception as e:
        raise ConfigError(f"CONFIG_FAIL invalid={name} action=\"Set {name} to an integer\"") from e


def env_float(name: str, *, default: float | None = None, required: bool = False, env: Mapping[str, str] | None = None) -> float | None:
    raw = env_str(name, default=None, required=required, env=env)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception as e:
        raise ConfigError(f"CONFIG_FAIL invalid={name} action=\"Set {name} to a float\"") from e


def env_bool(name: str, *, default: bool | None = None, env: Mapping[str, str] | None = None) -> bool | None:
    raw = env_str(name, default=None, required=False, env=env)
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ConfigError(f"CONFIG_FAIL invalid={name} action=\"Set {name} to true/false\"")


def env_csv(name: str, *, default: list[str] | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    raw = env_str(name, default=None, required=False, env=env)
    if raw is None:
        return list(default or [])
    parts = [p.strip() for p in str(raw).split(",")]
    return [p for p in parts if p]

