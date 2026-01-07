from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, TypedDict

from research.experiments.contract import ExperimentSpec


class ExperimentEntry(TypedDict):
    spec: ExperimentSpec
    run: Callable[[ExperimentSpec, Path], dict]


def _project_root() -> Path:
    # repo root is cwd for normal usage; resolve defensively
    return Path(__file__).resolve().parents[2]


# --- Import experiments (explicit registry = auditable and stable) ---
from research.experiments.gamma_signal_sanity import DEFAULT_SPEC as _GAMMA_SPEC  # noqa: E402
from research.experiments.gamma_signal_sanity import run as _GAMMA_RUN  # noqa: E402


EXPERIMENTS: dict[str, ExperimentEntry] = {
    _GAMMA_SPEC.experiment_id: {
        "spec": _GAMMA_SPEC,
        "run": _GAMMA_RUN,
    }
}


def list_experiments() -> list[ExperimentSpec]:
    return [entry["spec"] for entry in EXPERIMENTS.values()]


def get_experiment(experiment_id: str) -> ExperimentEntry:
    if experiment_id not in EXPERIMENTS:
        raise KeyError(f"Unknown experiment_id: {experiment_id}")
    return EXPERIMENTS[experiment_id]


def spec_with_output_dir(spec: ExperimentSpec, output_dir: Path) -> ExperimentSpec:
    # Immutable dataclass: return a new spec with output_dir set
    return replace(spec, output_dir=str(output_dir))

