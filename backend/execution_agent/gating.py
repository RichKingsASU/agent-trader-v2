from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Mapping, NoReturn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(env: Mapping[str, str], name: str) -> str | None:
    v = env.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


def evaluate_startup_gate(env: Mapping[str, str]) -> tuple[bool, list[str]]:
    """
    Hard gate for execution agent startup.

    Must be impossible to enable accidentally:
    - comparisons are strict, case-sensitive
    - this agent is OBSERVE-only (never places orders)
    - BROKER_EXECUTION_ENABLED must be present AND exactly "false"
    """
    reason_codes: list[str] = []

    required_exact: dict[str, str] = {
        "REPO_ID": "agent-trader-v2",
        "AGENT_NAME": "execution-agent",
        "AGENT_ROLE": "execution",
        # Repo policy: OBSERVE must work; EXECUTE is forbidden in committed configs.
        "AGENT_MODE": "OBSERVE",
        "EXECUTION_AGENT_ENABLED": "true",
    }

    for k, expected in required_exact.items():
        actual = _env(env, k)
        if actual is None:
            reason_codes.append(f"{k}_missing")
        elif actual != expected:
            reason_codes.append(f"{k}_mismatch")

    broker_enabled = _env(env, "BROKER_EXECUTION_ENABLED")
    if broker_enabled is None:
        reason_codes.append("BROKER_EXECUTION_ENABLED_missing")
    elif broker_enabled != "false":
        reason_codes.append("BROKER_EXECUTION_ENABLED_not_false")

    return (len(reason_codes) == 0, reason_codes)


def refuse_startup(*, reason_codes: list[str]) -> NoReturn:
    """
    Emit a single structured log event then exit non-zero.
    """
    payload = {
        "ts": _utc_now_iso(),
        "intent_type": "execution_agent_startup_refused",
        "reason_codes": list(reason_codes),
        "required_gate": {
            "REPO_ID": "agent-trader-v2",
            "AGENT_NAME": "execution-agent",
            "AGENT_ROLE": "execution",
            "AGENT_MODE": "OBSERVE",
            "EXECUTION_AGENT_ENABLED": "true",
            "BROKER_EXECUTION_ENABLED": "false",
        },
    }
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)
    raise SystemExit(2)


def enforce_startup_gate_or_exit() -> None:
    ok, reasons = evaluate_startup_gate(os.environ)  # type: ignore[arg-type]
    if ok:
        return
    refuse_startup(reason_codes=reasons)

