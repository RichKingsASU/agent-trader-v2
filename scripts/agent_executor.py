#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import os

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.lib.exec_guard as exec_guard

TASK_DIR = Path(".agent_tasks")
TASK_FILE = TASK_DIR / "commands.json"


def run_shell(cmd: str, *, cwd: str | None = None, env: dict[str, str] | None = None) -> dict:
    print(f"[agent_executor] RUN:", cmd, flush=True)
    # Use bash for consistent behavior across environments (e.g. $VAR, &&, pipefail-ish usage).
    proc = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main():
    if not TASK_FILE.exists():
        print(f"[agent_executor] No {TASK_FILE} found. Create it with a list of shell commands.")
        print('Example:\n{"commands": ["ls -la", "python -m compileall backend"]}')
        sys.exit(0)

    data = json.loads(TASK_FILE.read_text())
    commands = data.get("commands", [])
    results = []

    # Allow commands.json to define a stable working directory.
    # - If omitted, use $REPO_DIR if set, otherwise use the current directory.
    repo_dir = data.get("repo_dir") or os.getenv("REPO_DIR") or os.getcwd()
    repo_dir = os.path.expanduser(str(repo_dir))

    base_env = os.environ.copy()
    base_env["REPO_DIR"] = repo_dir

    for cmd in commands:
        if not isinstance(cmd, str):
            continue
        results.append(run_shell(cmd, cwd=repo_dir, env=base_env))

    TASK_DIR.mkdir(parents=True, exist_ok=True)
    out_file = TASK_DIR / "commands_result.json"
    out = {
        "ran_at": datetime.utcnow().isoformat(),
        "results": results,
        "repo_dir": repo_dir,
    }
    out_file.write_text(json.dumps(out, indent=2))
    print(f"[agent_executor] Done. Results written to {out_file}")


if __name__ == "__main__":
    exec_guard.enforce_execution_policy(__file__, sys.argv)
    main()
