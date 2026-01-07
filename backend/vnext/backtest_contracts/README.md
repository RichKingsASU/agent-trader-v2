# vNEXT Backtest Contracts (Deterministic Interfaces)

This package defines **interface-only** contracts for deterministic backtests.
It contains **no implementations** and **no backtest logic**.

## Non-negotiable constraints

- **No parameter tuning inside backtests**
  - A backtest run is a deterministic evaluation of a strategy with **fixed**
    `BacktestConfig.strategy_params`.
  - Optimization / hyperparameter search / walk-forward tuning must live
    *outside* the backtest runner, by orchestrating multiple independent runs.

- **Same code paths as live OBSERVE**
  - Backtests must reuse the **same OBSERVE-only strategy logic** used in live
    mode (same indicator calculations, same proposal generation, same risk
    gating), with only the data source swapped to recorded/snapshot data.
  - Avoid any “if backtest: …” branches that change strategy semantics.

## Determinism requirements (contract-level)

`BacktestConfig` includes explicit determinism anchors:
- **`data_snapshot_id`**: identifies the exact dataset snapshot used.
- **`engine_version`**: identifies the code/build that ran the backtest.
- **`random_seed`**: controls any randomness (if used at all).

## Public interfaces

- **Data contracts**
  - `BacktestConfig`
  - `BacktestRun`
  - `BacktestArtifact`

- **Runner interface**
  - `run_backtest(strategy_id, config)` (function signature)
  - `BacktestRunner.run_backtest(strategy_id, config)` (Protocol boundary)

