from __future__ import annotations

import os
from typing import Any, Mapping

# Pub/Sub attribute contract (required on every published message).
#
# Rules:
# - keys are lowercase snake_case
# - values are non-empty strings
# - payload bodies MUST NOT be modified to satisfy this contract

REQUIRED_PUBSUB_ATTRIBUTES: tuple[str, ...] = (
    "event_type",
    "schema_version",
    "producer",
    "environment",
)

# Schema version for the canonical Python `EventEnvelope` payload in this repo.
# Note: this is intentionally an attribute (not a payload field).
EVENT_ENVELOPE_SCHEMA_VERSION = "1"


def _clean(v: Any, *, max_len: int = 256) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


def resolve_environment() -> str:
    """
    Best-effort runtime environment identifier for message attribution.

    Producers SHOULD set one of these env vars:
    - ENVIRONMENT (preferred)
    - ENV (common in Cloud Run deploys)
    """
    for k in ("ENVIRONMENT", "ENV", "APP_ENV", "DEPLOY_ENV", "STAGE"):
        v = os.getenv(k)
        if v and str(v).strip():
            return _clean(v, max_len=64)
    return "unknown"


def build_standard_attributes(
    *,
    event_type: str,
    schema_version: str,
    producer: str,
    environment: str,
) -> dict[str, str]:
    attrs = {
        "event_type": _clean(event_type, max_len=256),
        "schema_version": _clean(schema_version, max_len=32),
        "producer": _clean(producer, max_len=128),
        "environment": _clean(environment, max_len=64),
    }
    validate_standard_attributes(attrs)
    return attrs


def validate_standard_attributes(attributes: Mapping[str, Any]) -> dict[str, str]:
    """
    Validate required attributes are present and non-empty.

    Returns a normalized dict[str, str] for the required keys.
    Raises ValueError on contract violations.
    """
    normalized: dict[str, str] = {}
    missing: list[str] = []
    for k in REQUIRED_PUBSUB_ATTRIBUTES:
        v = attributes.get(k) if attributes is not None else None
        sv = _clean(v)
        if not sv:
            missing.append(k)
            continue
        normalized[k] = sv
    if missing:
        raise ValueError(f"Missing required Pub/Sub attributes: {', '.join(missing)}")
    return normalized

