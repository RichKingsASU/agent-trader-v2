## Stress Replay & Historical Simulation (vNEXT)

This package defines **deterministic replay contracts** for stress testing strategies against historical inputs.

### Non-negotiables

- **Same code paths as live**: replay must execute strategies through the same entrypoints used in production (only the clock + data sources are swapped for historical snapshots).
- **No parameter tuning during replay**: replays must not mutate strategy parameters mid-run and must not accept per-run “optimization” overrides.

### Contracts

Defined in `backend/vnext/stress_replay/interfaces.py`:

- **`ReplayScenario`**: describes *what* is replayed (time window, immutable input references, determinism seed).
- **`ReplayConfig`**: describes *how* it is replayed (determinism rails; explicitly disallows parameter tuning).
- **`ReplayResult`**: describes *what* the run produced (status, metrics, artifact URIs, errors).
- **`run_replay(strategy_id, scenario_id)`**: minimal interface exposed via `ReplayRunner`.

