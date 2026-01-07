# Research Factory (AgentTrader v2) — Safe, Reproducible, Auditable

This folder scaffolds an **institutional “research factory”** that can run experiments deterministically, log results with build fingerprints, and generate artifacts that can later be **promoted** into strategy configs **safely**.

## Safety rules (non-negotiable)

- **No trading execution**: research code must never place orders or call execution paths.
- **No proprietary / external data dependencies**: experiments run on file-based dataset snapshots (or synthetic data).
- **Reproducible & auditable**: each run writes a complete spec + build fingerprint + agent identity.
- **Promotion is safe-by-default**: generated strategy configs are **disabled**, **EVAL_ONLY**, and **requires_human_approval=true**.

## Directory layout

- `research/experiments/`: experiment implementations + registry
- `research/datasets/`: dataset snapshots (file-based, versioned)
- `research/results/`: run outputs (spec, metrics, artifacts)
- `research/promotion/`: promotion tools (result → strategy config)

## Dataset snapshots convention

Datasets live under:

`research/datasets/<dataset_name>/<version>/`

Each version folder must include a `manifest.json` describing the source and integrity:

- `source`: where it came from (URL, query, synthetic generator, etc.)
- `created_at`: ISO timestamp
- `schema`: free-form schema description
- `checksums`: sha256 per file (or other checksum map)

No real data is required in-repo; the convention is what matters.

## Experiments

Experiments are registered in `research/experiments/registry.py`. Each experiment provides:

- a default `ExperimentSpec` (metadata + dataset path + parameters + metrics list)
- a `run(spec, output_dir)` function that writes artifacts and returns metrics

### Add a new experiment

1) Create a module in `research/experiments/` (e.g. `my_experiment.py`)
2) Implement:
   - `DEFAULT_SPEC` (`ExperimentSpec`)
   - `run(spec: ExperimentSpec, output_dir: pathlib.Path) -> dict`
3) Register it in `research/experiments/registry.py`

## Running experiments (CLI-first)

List experiments:

```bash
python scripts/run_experiment.py --list
```

Run an experiment:

```bash
python scripts/run_experiment.py --id gamma_signal_sanity
```

Override parameters:

```bash
python scripts/run_experiment.py --id gamma_signal_sanity --param n_days=504 --param ma_window=30
```

## Outputs

Each run writes to:

`research/results/<experiment_id>/<run_id>/`

Containing:

- `spec.json`: experiment spec + runtime/build/agent provenance
- `metrics.json`: metrics emitted by the experiment
- `artifacts/`: any additional outputs (plots, series dumps, intermediate files)

## Promotion workflow (safe-by-default)

Promotion takes a completed result run and generates/updates a config file:

`configs/strategies/<strategy>.yaml`

Promotion never enables trading. It always writes:

- `enabled: false`
- `mode: EVAL_ONLY`
- `requires_human_approval: true`

Usage example:

```bash
python research/promotion/promote_to_strategy_config.py --experiment-id gamma_signal_sanity --run-id <run_id> --strategy gamma_sanity_eval
```

