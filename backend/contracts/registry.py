from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class SchemaValidationError(ValueError):
    topic: str
    schema_path: str
    errors: list[dict[str, Any]]

    def __str__(self) -> str:  # pragma: no cover (pretty string only)
        return (
            f"schema_validation_failed topic={self.topic} schema={self.schema_path} "
            f"errors={len(self.errors)}"
        )


def _repo_root() -> Path:
    # backend/contracts/registry.py -> backend/contracts -> backend -> repo root
    return Path(__file__).resolve().parents[2]


def get_schema_path_for_topic(topic: str) -> Path:
    t = (topic or "").strip()
    if not t:
        raise ValueError("missing_topic")

    # Allow fully-qualified Pub/Sub topic paths.
    # Example: projects/<p>/topics/market-bars-1m
    if "/topics/" in t:
        t = t.split("/topics/")[-1].strip()

    # Canonical topics covered by this gate.
    allowed = {"system-events", "market-ticks", "market-bars-1m", "trade-signals"}
    if t not in allowed:
        raise ValueError(f"unsupported_topic:{t}")

    return _repo_root() / "contracts" / "schemas" / f"{t}.v1.schema.json"


@lru_cache(maxsize=64)
def _load_schema(schema_path: str) -> dict[str, Any]:
    p = Path(schema_path)
    raw = p.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"schema_not_object:{schema_path}")
    return obj


@lru_cache(maxsize=64)
def get_validator_for_topic(topic: str):
    # Lazy import so services that don't need contract validation can still import.
    from jsonschema import Draft202012Validator  # type: ignore

    schema_path = str(get_schema_path_for_topic(topic))
    schema = _load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_topic_event(*, topic: str, event: Any) -> Optional[list[dict[str, Any]]]:
    """
    Validate an event payload (decoded JSON) for the given Pub/Sub topic.

    Returns:
    - None if valid
    - list[error] if invalid (stable, JSON-serializable)
    """
    if event is None:
        return [{"path": "", "message": "event_is_null"}]
    if not isinstance(event, dict):
        return [{"path": "", "message": f"event_not_object:{type(event).__name__}"}]

    validator = get_validator_for_topic(topic)
    errors: list[dict[str, Any]] = []
    for e in sorted(validator.iter_errors(event), key=lambda x: (list(x.path), str(x.message))):
        path = ".".join(str(p) for p in e.path)
        errors.append(
            {
                "path": path,
                "message": str(e.message),
                "schema_path": "/".join(str(p) for p in e.schema_path),
            }
        )
        if len(errors) >= 50:
            break
    return None if not errors else errors

