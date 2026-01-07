from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys


def test_gamma_signal_sanity_creates_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "scripts" / "run_experiment.py"
    assert runner.exists()

    # Use default results location (research/results) to validate the contract.
    p = subprocess.run(
        [sys.executable, str(runner), "--id", "gamma_signal_sanity"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout:\n{p.stdout}\n\nstderr:\n{p.stderr}"

    run_dir: Path | None = None
    for line in p.stdout.splitlines():
        if line.startswith("Run directory:"):
            run_dir = Path(line.split("Run directory:", 1)[1].strip())
            break
    assert run_dir is not None, f"Could not parse run directory from stdout:\n{p.stdout}"
    assert run_dir.exists()

    try:
        spec_path = run_dir / "spec.json"
        metrics_path = run_dir / "metrics.json"
        artifacts_dir = run_dir / "artifacts"

        assert spec_path.exists()
        assert metrics_path.exists()
        assert artifacts_dir.exists()

        spec_obj = json.loads(spec_path.read_text())
        metrics_obj = json.loads(metrics_path.read_text())

        # Required keys / structure
        assert "spec" in spec_obj
        assert "runtime" in spec_obj
        assert spec_obj["spec"]["experiment_id"] == "gamma_signal_sanity"
        assert "seed" in spec_obj["spec"]
        assert "build_id" in spec_obj["spec"]

        assert metrics_obj["experiment_id"] == "gamma_signal_sanity"
        assert "run_id" in metrics_obj
        assert "metrics" in metrics_obj
        for k in ("sharpe_like", "hit_rate", "max_drawdown"):
            assert k in metrics_obj["metrics"]

        # Example artifacts
        assert (artifacts_dir / "series_summary.json").exists()
        assert (artifacts_dir / "equity_curve.csv").exists()
    finally:
        # Keep workspace clean for repeated runs.
        shutil.rmtree(run_dir, ignore_errors=True)

