#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_loads_best_effort(s: str) -> Any:
    """
    Allow --param x=1, x=true, x=[1,2], x="str" via JSON.
    Fallback to raw string if parsing fails.
    """
    try:
        return json.loads(s)
    except Exception:
        return s


def _safe_git_sha() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        sha = out.decode("utf-8").strip()
        return sha if sha else None
    except Exception:
        return None


def _safe_git_dirty() -> bool | None:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL)
        return bool(out.decode("utf-8").strip())
    except Exception:
        return None


def _dataset_fingerprint(dataset_path: Path) -> dict[str, Any]:
    """
    Best-effort dataset snapshot fingerprint for auditability.
    """
    info: dict[str, Any] = {"path": str(dataset_path), "exists": dataset_path.exists()}
    if not dataset_path.exists():
        return info

    manifest_path = dataset_path / "manifest.json"
    if manifest_path.exists():
        try:
            info["manifest"] = json.loads(manifest_path.read_text())
        except Exception as e:
            info["manifest_error"] = f"{type(e).__name__}: {e}"

    # Compute sha256 for all files (stable ordering)
    file_hashes: dict[str, str] = {}
    for p in sorted(dataset_path.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(dataset_path))
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            file_hashes[rel] = h
    info["computed_sha256"] = file_hashes
    return info


def _run_fingerprint(spec_dict: dict[str, Any], dataset_fp: dict[str, Any]) -> str:
    """
    Deterministic fingerprint for the run inputs + build provenance.
    """
    payload = {
        "spec": spec_dict,
        "dataset": dataset_fp.get("computed_sha256") or {},
    }
    b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Research experiment runner (safe, deterministic, auditable).")
    parser.add_argument("--list", action="store_true", help="List registered experiments")
    parser.add_argument("--id", dest="experiment_id", help="Run experiment by experiment_id")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Override parameter key=value (repeatable). Value supports JSON.",
    )
    parser.add_argument(
        "--results-root",
        default="research/results",
        help="Root directory for results (default: research/results).",
    )

    args = parser.parse_args()

    # Ensure repo root on sys.path so `import research...` works when run as a script.
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from research.experiments.contract import agent_identity  # noqa: E402
    from research.experiments.registry import get_experiment, list_experiments, spec_with_output_dir  # noqa: E402

    if args.list:
        for spec in list_experiments():
            print(f"{spec.experiment_id}\t{spec.name}")
        return 0

    if not args.experiment_id:
        parser.error("Provide --list or --id <experiment_id>")

    entry = get_experiment(args.experiment_id)
    base_spec = entry["spec"]
    run_fn = entry["run"]

    # Apply overrides to parameters (only)
    params = dict(base_spec.parameters or {})
    for kv in args.param:
        if "=" not in kv:
            raise SystemExit(f"Invalid --param '{kv}'. Expected key=value")
        k, v = kv.split("=", 1)
        params[k] = _json_loads_best_effort(v)

    # Create run directory
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    results_root = (repo_root / args.results_root).resolve()
    run_dir = results_root / base_spec.experiment_id / run_id
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Inject output_dir + parameters into the immutable spec
    spec = base_spec.with_overrides(parameters=params)
    spec = spec_with_output_dir(spec, run_dir)

    dataset_path = (repo_root / spec.input_dataset).resolve() if not Path(spec.input_dataset).is_absolute() else Path(spec.input_dataset)
    dataset_fp = _dataset_fingerprint(dataset_path)

    spec_dict = spec.to_dict()
    runtime = {
        "run_id": run_id,
        "run_fingerprint": _run_fingerprint(spec_dict, dataset_fp),
        "started_at": _utc_now_iso(),
        "cwd": os.getcwd(),
        "python": sys.version,
        "platform": platform.platform(),
        "git_sha": _safe_git_sha(),
        "git_dirty": _safe_git_dirty(),
        "agent": agent_identity(),
        "dataset_snapshot": dataset_fp,
    }

    t0 = time.time()
    (run_dir / "spec.json").write_text(
        json.dumps({"spec": spec_dict, "runtime": runtime}, indent=2, sort_keys=True) + "\n"
    )

    # Run experiment (must be deterministic given same seed + dataset snapshot)
    metrics_obj = run_fn(spec, run_dir)

    runtime["finished_at"] = _utc_now_iso()
    runtime["duration_sec"] = round(time.time() - t0, 6)

    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_fingerprint": runtime["run_fingerprint"],
                "experiment_id": spec.experiment_id,
                "metrics": metrics_obj.get("metrics", metrics_obj),
                "provenance": {
                    "build_id": spec.build_id,
                    "git_sha": spec.git_sha,
                    "agent": runtime["agent"],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    # Update spec.json with final timestamps (without changing spec)
    (run_dir / "spec.json").write_text(
        json.dumps({"spec": spec_dict, "runtime": runtime}, indent=2, sort_keys=True) + "\n"
    )

    print(f"Run ID: {run_id}")
    print(f"Run directory: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

