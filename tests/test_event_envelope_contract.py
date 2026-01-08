import json
import subprocess
from pathlib import Path

from backend.messaging.envelope import EventEnvelope


def test_python_event_envelope_matches_typescript_schema_json_level() -> None:
    """
    Contract test:
    - Produce a Python `EventEnvelope`
    - Validate the decoded JSON matches the TS-side JSON schema/validator
      (implemented as a runtime validator exported from shared-types dist).
    """

    env = EventEnvelope.new(
        event_type="contract.test",
        agent_name="pytest",
        git_sha="deadbeef",
        ts="2026-01-08T00:00:00+00:00",
        trace_id="trace123",
        payload={
            "k": "v",
            "n": 1,
            "ok": True,
            "nested": {"x": 1},
            "arr": [1, 2, 3],
        },
    )

    payload_json = json.dumps(env.to_dict(), separators=(",", ":"), ensure_ascii=False)

    dist_envelope_js = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "shared-types"
        / "dist"
        / "envelope.js"
    )
    assert dist_envelope_js.exists(), f"Missing TS validator: {dist_envelope_js}"

    node_script = f"""
      const fs = require('fs');
      const {{ isEventEnvelope }} = require({json.dumps(str(dist_envelope_js))});
      const input = fs.readFileSync(0, 'utf8').trim();
      const obj = JSON.parse(input);
      if (!isEventEnvelope(obj)) {{
        console.error('TS schema validation failed for EventEnvelope:', obj);
        process.exit(1);
      }}
    """

    res = subprocess.run(
        ["node", "-e", node_script],
        input=payload_json.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert (
        res.returncode == 0
    ), f"Node/TS schema validation failed:\nSTDERR:\n{res.stderr.decode('utf-8')}\nSTDOUT:\n{res.stdout.decode('utf-8')}"

