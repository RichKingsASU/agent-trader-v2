#!/usr/bin/env python3
"""
CI-safe validation: emit sample intent logs and validate required keys exist.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path


REQUIRED_KEYS = {
    "timestamp",
    "level",
    "repo_id",
    "agent_name",
    "agent_role",
    "agent_mode",
    "git_sha",
    "intent_id",
    "correlation_id",
    "trace_id",
    "intent_type",
    "intent_summary",
    "intent_payload",
    "outcome",
}


def main() -> int:
    # Ensure repo root is on sys.path when invoked from anywhere.
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    os.environ.setdefault("REPO_ID", "agent-trader-v2")
    os.environ.setdefault("AGENT_NAME", "validate-intent-logging")
    os.environ.setdefault("AGENT_ROLE", "ops")
    os.environ.setdefault("AGENT_MODE", "OFF")
    os.environ.setdefault("GIT_SHA", "deadbeef")

    from backend.observability.logger import intent_start, intent_end

    buf = io.StringIO()
    with redirect_stdout(buf):
        ctx = intent_start("agent_start", "Validate intent logging schema.", payload={"api_key": "nope"})
        intent_end(ctx, "success")

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    if len(lines) < 2:
        print("ERROR: expected >=2 log lines", file=sys.stderr)
        return 2

    for ln in lines[-2:]:
        obj = json.loads(ln)
        missing = sorted(REQUIRED_KEYS - set(obj.keys()))
        if missing:
            print(f"ERROR: missing keys: {missing}", file=sys.stderr)
            print("LOG:", ln, file=sys.stderr)
            return 3

        # Basic redaction sanity: api_key should not be the raw value.
        if obj.get("intent_payload", {}).get("api_key") == "nope":
            print("ERROR: redaction failed (api_key leaked)", file=sys.stderr)
            return 4

    print("ok: intent logging schema valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

