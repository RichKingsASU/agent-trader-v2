from __future__ import annotations

from pathlib import Path


def test_repo_structure_contract__single_source_of_truth() -> None:
    """
    Repo layout contract (CI-enforced):
    - Ops UI must live at frontend/ops-ui
    - Legacy duplicate apps/ops-dashboard must not exist
    """
    repo_root = Path(__file__).resolve().parents[1]

    # Ops UI (canonical)
    assert (repo_root / "frontend" / "ops-ui" / "package.json").is_file()
    assert (repo_root / "firebase.json").is_file()

    # Legacy duplicate (removed)
    assert not (repo_root / "apps" / "ops-dashboard").exists()


def test_repo_structure_contract__workflows_reference_canonical_paths() -> None:
    """
    Workflows must build the canonical Ops UI, not a legacy workspace root.
    """
    repo_root = Path(__file__).resolve().parents[1]
    ci_yml = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deploy_yml = (repo_root / ".github" / "workflows" / "firebase_ops_dashboard_deploy.yml").read_text(
        encoding="utf-8"
    )

    # Prevent accidental re-introduction of the removed legacy surface.
    assert "apps/ops-dashboard" not in ci_yml
    assert "apps/ops-dashboard" not in deploy_yml

    # Ensure workflows build the real package that has a lockfile.
    assert "frontend/ops-ui" in ci_yml
    assert "frontend/ops-ui" in deploy_yml

