from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from backend.messaging.envelope import EventEnvelope


def _repo_root() -> Path:
    # tests/ is directly under repo root in this workspace
    return Path(__file__).resolve().parents[1]


def _load_ts_event_envelope_required_keys() -> list[str]:
    """
    Extract required keys from the TS shared contract type:
      packages/shared-types/src/envelope.ts

    We intentionally keep this lightweight (regex-based) to avoid adding new deps.
    """
    ts_path = _repo_root() / "packages" / "shared-types" / "src" / "envelope.ts"
    text = ts_path.read_text(encoding="utf-8")

    # Capture the object literal for:
    #   export type EventEnvelope<...> = { ... };
    m = re.search(
        r"export\s+type\s+EventEnvelope\b[\s\S]*?=\s*\{([\s\S]*?)\};",
        text,
        flags=re.MULTILINE,
    )
    if not m:
        raise AssertionError(f"Could not locate TS EventEnvelope type in {ts_path}")

    body = m.group(1)
    keys: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        km = re.match(r"^([A-Za-z_]\w*)\s*:", stripped)
        if km:
            keys.append(km.group(1))

    if not keys:
        raise AssertionError(f"Parsed zero keys from TS EventEnvelope in {ts_path}")

    # EventEnvelopeV1 extends EventEnvelope and adds schemaVersion: 1.
    if "schemaVersion" not in keys:
        keys.append("schemaVersion")

    # Ensure stable order and no dupes (helps debugging on drift).
    deduped = list(dict.fromkeys(keys))
    if len(deduped) != len(keys):
        raise AssertionError(f"Duplicate keys parsed from TS EventEnvelope in {ts_path}: {keys}")
    return deduped


class TestPubSubEnvelopeContractGate(unittest.TestCase):
    def test_pubsub_event_envelope_python_matches_ts_shared_types_contract(self) -> None:
        """
        Contract gate: prevent drift between Python Pub/Sub envelope and TS consumer types.

        Constraints:
        - No producer logic changes
        - No schema changes
        - Test must generate a real Python EventEnvelope and validate its JSON shape
        """
        ts_keys = _load_ts_event_envelope_required_keys()

        envelope = EventEnvelope.new(
            event_type="contract.test",
            agent_name="contract-gate",
            payload={"hello": "world", "n": 1, "ok": True},
            trace_id="deadbeef" * 4,  # 32 hex chars; stable for assertions
            git_sha="abc123def456",
            ts="2026-01-08T00:00:00+00:00",
        )

        # Serialize the actual producer-side envelope to JSON.
        raw_json = envelope.to_json()
        decoded = json.loads(raw_json)
        self.assertIsInstance(decoded, dict, "Envelope JSON must decode to an object")

        # Key-set gate: TS-required keys must match Python envelope keys exactly.
        py_keys = list(decoded.keys())
        self.assertEqual(
            set(py_keys),
            set(ts_keys),
            "EventEnvelope key drift detected between Python and TS.\n"
            f"TS keys: {ts_keys}\n"
            f"PY keys: {sorted(py_keys)}\n",
        )

        # Runtime type gate (what the dashboard consumer expects at runtime).
        self.assertIsInstance(decoded["event_type"], str)
        self.assertTrue(decoded["event_type"])
        self.assertIsInstance(decoded["agent_name"], str)
        self.assertTrue(decoded["agent_name"])
        self.assertIsInstance(decoded["git_sha"], str)
        self.assertTrue(decoded["git_sha"])
        self.assertIsInstance(decoded["ts"], str)
        self.assertTrue(decoded["ts"])
        self.assertIsInstance(decoded["trace_id"], str)
        self.assertTrue(decoded["trace_id"])
        self.assertIsInstance(decoded["payload"], dict)

