from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_generate_blueprint_runs_and_has_required_headings() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "generate_blueprint.py"
    assert script.exists()

    subprocess.run([sys.executable, str(script), "--quiet"], cwd=str(repo_root), check=True)

    out = repo_root / "docs" / "BLUEPRINT.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8", errors="replace")

    required_headings = [
        "# AgentTrader v2 — Repo Blueprint",
        "## Executive Snapshot (what v2 is + safety posture)",
        "## Component Inventory (table)",
        "## Build Pipelines (table)",
        "## Safety Controls",
        "## Ops Commands",
        "## Known Gaps (automatically inferred)",
        "## Links (docs index)",
    ]
    for h in required_headings:
        assert h in text

