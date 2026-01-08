from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional


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

    Cross-language reference:
      - TypeScript: packages/shared-types/src/envelope.ts
    """

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
    ) -> "EventEnvelope":
        return EventEnvelope(
            event_type=str(event_type),
            agent_name=str(agent_name),
            git_sha=str(git_sha or _default_git_sha()),
            ts=str(ts or _utc_now_iso()),
            payload=dict(payload or {}),
            trace_id=str(trace_id or uuid.uuid4().hex),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
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
        return EventEnvelope(
            event_type=str(data["event_type"]),
            agent_name=str(data["agent_name"]),
            git_sha=str(data["git_sha"]),
            ts=str(data["ts"]),
            payload=dict(data.get("payload") or {}),
            trace_id=str(data["trace_id"]),
        )

    @staticmethod
    def from_bytes(data: bytes) -> "EventEnvelope":
        decoded = json.loads(data.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("EventEnvelope JSON must decode to an object")
        return EventEnvelope.from_dict(decoded)

