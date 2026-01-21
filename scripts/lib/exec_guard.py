"""
Execution guard for high-risk repo scripts.

Goal:
- Prevent accidental execution of high-blast-radius scripts in CI or production-like runtimes.
- Require an explicit local opt-in for MUST_LOCK scripts.

This module is intentionally dependency-free and safe to import early.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class ScriptRisk(str, Enum):
    SAFE = "SAFE"
    HIGH = "HIGH"
    MUST_LOCK = "MUST_LOCK"


@dataclass(frozen=True)
class Policy:
    risk: ScriptRisk
    note: str


_CALLED = False


def _repo_root_from(path: Path) -> Path:
    """
    Best-effort repo root detection.
    - Prefer a parent containing `.git/`
    - Otherwise fallback to parent-of-scripts style layout.
    """
    p = path.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    # Most scripts are /repo/scripts/<name>.py
    if "scripts" in p.parts:
        try:
            idx = list(p.parts).index("scripts")
            if idx > 0:
                return Path(*p.parts[:idx])
        except Exception:
            pass
    return p.parent


def _is_ci() -> bool:
    return str(os.getenv("GITHUB_ACTIONS") or "").strip() == "true" or str(os.getenv("CI") or "").strip() == "true"


def _is_runtime_like() -> bool:
    # Cloud Run sets K_SERVICE; Kubernetes sets KUBERNETES_SERVICE_HOST.
    if (os.getenv("K_SERVICE") or "").strip():
        return True
    if (os.getenv("KUBERNETES_SERVICE_HOST") or "").strip():
        return True
    return False


def _rel_script(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _policies() -> dict[str, Policy]:
    """
    Canonical classification for scripts that require guard enforcement.

    Key: repo-relative path (POSIX style).
    """
    return {
        # MUST_LOCK: explicit local opt-in required.
        "scripts/agent_executor.py": Policy(
            risk=ScriptRisk.MUST_LOCK,
            note="Runs arbitrary shell commands from a task file (high blast radius).",
        ),
        "scripts/place_test_order.py": Policy(
            risk=ScriptRisk.MUST_LOCK,
            note="Places a broker order (even if paper).",
        ),
        "scripts/insert_paper_order.py": Policy(
            risk=ScriptRisk.MUST_LOCK,
            note="Places a broker order and/or writes trading artifacts.",
        ),
        "backend/strategy_service/scripts/insert_paper_order.py": Policy(
            risk=ScriptRisk.MUST_LOCK,
            note="Writes paper order rows to the database.",
        ),
        "scripts/init_shadow_mode_config.py": Policy(
            risk=ScriptRisk.MUST_LOCK,
            note="Mutates runtime safety posture (shadow mode) in Firestore.",
        ),
        # HIGH: blocked in CI/runtime-like contexts.
        "scripts/emit_chaos_pubsub_events.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Emits events to an HTTP endpoint; can impact services.",
        ),
        "cloudrun_consumer/scripts/load_test_pubsub_push.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Load tests an HTTP endpoint; can cause denial-of-service.",
        ),
        "scripts/seed_whale_flow_data.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Writes test data to Firestore.",
        ),
        "scripts/seed_sentiment_data.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Writes seed data (may mutate Firestore).",
        ),
        "scripts/populate_whale_flow_test_data.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Populates test data (mutating operation).",
        ),
        "scripts/populate_institutional_features_data.py": Policy(
            risk=ScriptRisk.HIGH,
            note="Populates institutional features data (mutating operation).",
        ),
    }


def iter_guarded_scripts() -> Iterable[str]:
    """
    Exposed for validation: list of scripts classified as HIGH or MUST_LOCK.
    """
    return tuple(sorted(_policies().keys()))


def enforce_execution_policy(script_path: str, argv: list[str]) -> None:
    """
    Enforce policy for HIGH / MUST_LOCK scripts.

    Requirements:
    - Abort cleanly with a clear error message.
    - Ensure guard is invoked exactly once per process.
    """
    global _CALLED
    if _CALLED:
        raise SystemExit("ERROR: exec_guard invoked multiple times; expected exactly once per script.")
    _CALLED = True

    _ = argv  # keep signature stable; policy does not interpret flags.

    p = Path(script_path).resolve()
    repo = _repo_root_from(p)
    rel = _rel_script(p, repo)

    policy = _policies().get(rel)
    if policy is None or policy.risk == ScriptRisk.SAFE:
        return

    if _is_ci():
        raise SystemExit(
            f"REFUSED: {rel} is classified as {policy.risk} and must not run in CI.\n"
            f"Reason: {policy.note}"
        )

    if _is_runtime_like():
        raise SystemExit(
            f"REFUSED: {rel} is classified as {policy.risk} and must not run in production-like runtimes.\n"
            f"Reason: {policy.note}"
        )

    if policy.risk == ScriptRisk.MUST_LOCK:
        unlock = str(os.getenv("EXEC_GUARD_UNLOCK") or "").strip()
        if unlock != "1":
            raise SystemExit(
                f"REFUSED: {rel} is classified as MUST_LOCK and requires an explicit local unlock.\n"
                f"Set EXEC_GUARD_UNLOCK=1 to acknowledge and proceed.\n"
                f"Reason: {policy.note}"
            )

