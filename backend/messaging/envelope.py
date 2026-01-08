from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence


def _utc_now_iso() -> str:
    # RFC3339-ish ISO with explicit UTC offset
    return datetime.now(timezone.utc).isoformat()


def _default_git_sha() -> str:
    # Common envs used in CI/CD systems; fall back to "unknown".
    return (
        os.getenv("GIT_SHA")
        or os.getenv("GITHUB_SHA")
        or os.getenv("COMMIT_SHA")
        or "unknown"
    )


def _first_present(data: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in data:
            return data.get(k)
    return None


def _require_str(data: Mapping[str, Any], keys: Sequence[str], *, field_name: str) -> str:
    v = _first_present(data, keys)
    s = str(v).strip() if v is not None else ""
    if not s:
        raise ValueError(f"Missing required field: {field_name}")
    return s


def _require_int(data: Mapping[str, Any], keys: Sequence[str], *, field_name: str) -> int:
    v = _first_present(data, keys)
    if v is None:
        raise ValueError(f"Missing required field: {field_name}")
    try:
        # Accept numeric strings but keep the canonical type as int.
        return int(v)
    except Exception as e:
        raise ValueError(f"Invalid integer for field: {field_name}") from e


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """
    Canonical agent-to-agent message envelope.

    Required fields (per project contract):
      - event_type: stable event identifier (e.g. "marketdata.heartbeat")
      - agent_name: producer logical name (e.g. "marketdata", "strategy-engine")
      - git_sha: producer code version identifier
      - ts: ISO-8601 timestamp (UTC recommended)
      - payload: JSON-serializable object
      - trace_id: correlation id for distributed tracing/log stitching
      - schemaVersion: REQUIRED envelope schema version (this contract: 1)

    Cross-language reference:
      - TypeScript: packages/shared-types/src/envelope.ts
    """

    schemaVersion: int
    event_type: str
    agent_name: str
    git_sha: str
    ts: str
    payload: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @staticmethod
    def new(
        *,
        event_type: str,
        agent_name: str,
        payload: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
        git_sha: Optional[str] = None,
        ts: Optional[str] = None,
        schemaVersion: Optional[int] = None,
    ) -> "EventEnvelope":
        return EventEnvelope(
            schemaVersion=int(schemaVersion if schemaVersion is not None else 1),
            event_type=str(event_type),
            agent_name=str(agent_name),
            git_sha=str(git_sha or _default_git_sha()),
            ts=str(ts or _utc_now_iso()),
            payload=dict(payload or {}),
            trace_id=str(trace_id or uuid.uuid4().hex),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": int(self.schemaVersion),
            "event_type": self.event_type,
            "agent_name": self.agent_name,
            "git_sha": self.git_sha,
            "ts": self.ts,
            "payload": self.payload,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    def to_bytes(self) -> bytes:
        return self.to_json().encode("utf-8")

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "EventEnvelope":
        # Be tolerant of extra fields; enforce required ones.
        allow_legacy = (os.getenv("ALLOW_LEGACY_SCHEMALESS_ENVELOPE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        if ("schemaVersion" not in data) and ("schema_version" not in data):
            if allow_legacy:
                schema_version = 0
            else:
                raise ValueError("Missing required field: schemaVersion")
        else:
            schema_version = _require_int(
                data, ("schemaVersion", "schema_version"), field_name="schemaVersion"
            )

        return EventEnvelope(
            schemaVersion=int(schema_version),
            # Aliases (do not remove): eventType/type -> event_type
            event_type=_require_str(data, ("event_type", "eventType", "type"), field_name="event_type"),
            # Aliases (do not remove): agentName -> agent_name
            agent_name=_require_str(data, ("agent_name", "agentName"), field_name="agent_name"),
            # Aliases (do not remove): gitSha/sha -> git_sha
            git_sha=_require_str(data, ("git_sha", "gitSha", "sha"), field_name="git_sha"),
            # Aliases (do not remove): producedAt -> ts
            ts=_require_str(data, ("ts", "producedAt"), field_name="ts"),
            payload=dict(data.get("payload") or {}),
            # Aliases (do not remove): traceId -> trace_id
            trace_id=_require_str(data, ("trace_id", "traceId"), field_name="trace_id"),
        )

    @staticmethod
    def from_bytes(data: bytes) -> "EventEnvelope":
        decoded = json.loads(data.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("EventEnvelope JSON must decode to an object")
        return EventEnvelope.from_dict(decoded)

