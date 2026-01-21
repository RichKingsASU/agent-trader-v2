from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _json_safe(value: Any) -> Any:
    """
    Convert common non-JSON types into JSON-safe equivalents.

    This is deliberately conservative; unknown objects become strings to keep
    persistence robust for operator debugging/replay.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        v = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return v.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    return str(value)


@dataclass(frozen=True, slots=True)
class ExplanationRecord:
    """
    Persistable explanation artifact produced by an observer.

    Notes:
    - Stored as JSON Lines (one record per line).
    - No database writes; only optional local filesystem writes.
    """

    observer: str
    explanation: dict[str, Any]
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    record_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "record_id": str(self.record_id),
            "observer": str(self.observer),
            "created_at": _json_safe(self.created_at),
            "input": _json_safe(self.input),
            "explanation": _json_safe(self.explanation),
            "metadata": _json_safe(self.metadata),
        }

    def to_json(self) -> str:
        # Compact, stable JSON for JSONL storage.
        return json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "ExplanationRecord":
        if not isinstance(data, Mapping):
            raise TypeError("ExplanationRecord.from_json_dict expects a mapping")

        created_at = _coerce_dt(data.get("created_at")) or utcnow()

        observer = str(data.get("observer") or "").strip() or "unknown_observer"
        record_id = str(data.get("record_id") or data.get("id") or "").strip() or str(uuid4())

        inp = data.get("input")
        expl = data.get("explanation")
        meta = data.get("metadata")

        input_dict: MutableMapping[str, Any] = dict(inp) if isinstance(inp, Mapping) else {}
        explanation_dict: MutableMapping[str, Any] = dict(expl) if isinstance(expl, Mapping) else {}
        metadata_dict: MutableMapping[str, Any] = dict(meta) if isinstance(meta, Mapping) else {}

        schema_version = data.get("schema_version")
        try:
            sv = int(schema_version) if schema_version is not None else 1
        except Exception:
            sv = 1

        return cls(
            observer=observer,
            explanation=dict(explanation_dict),
            input=dict(input_dict),
            metadata=dict(metadata_dict),
            created_at=created_at,
            record_id=record_id,
            schema_version=sv,
        )

    @classmethod
    def from_json(cls, s: str) -> "ExplanationRecord":
        obj = json.loads(s)
        return cls.from_json_dict(obj)

    @staticmethod
    def sanitize_observer_name(name: str) -> str:
        """
        Used to derive filesystem paths from observer names.
        """
        raw = str(name or "").strip() or "unknown_observer"
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
        out = "".join(ch if ch in allowed else "_" for ch in raw)
        return out[:128] if len(out) > 128 else out

