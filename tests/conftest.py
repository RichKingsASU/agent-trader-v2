from __future__ import annotations

from pathlib import Path
import subprocess


def _cleanup_blueprint_artifacts() -> None:
    """
    Test hygiene: remove generated blueprint artifacts.

    Some tests (e.g. blueprint generators) may write into `audit_artifacts/`.
    Those files are not test assertions and should not persist between runs.
    """
    repo_root = Path(__file__).resolve().parents[1]
    d = repo_root / "audit_artifacts" / "blueprints"
    if not d.exists():
        return
    for p in d.glob("BLUEPRINT_*.md"):
        # Never delete tracked files.
        try:
            res = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(p)],
                cwd=str(repo_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if res.returncode == 0:
                continue
        except Exception:
            # If git isn't available for some reason, fail safe: don't delete.
            continue
        try:
            p.unlink()
        except Exception:
            # Best-effort cleanup; never fail tests due to filesystem issues.
            pass


def pytest_sessionstart(session) -> None:  # noqa: ARG001
    _cleanup_blueprint_artifacts()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    _cleanup_blueprint_artifacts()

