## Backtest runbook (paper-only)

This repo is **paper-only**. Backtests enforce:
- `TRADING_MODE=paper` (hard lock)
- `APCA_API_BASE_URL=https://paper-api.alpaca.markets` (hard assertion)
- `AGENT_MODE` must be explicitly set and must not allow execution

### Canonical entrypoints

- **CLI (canonical tonight)**: `scripts/run_backtest.py`
- **Engine (library)**: `functions/backtester.py`
- **Legacy example**: `scripts/run_backtest_example.py` (interactive; single symbol; 1m only)

### Required env vars

```bash
export AGENT_MODE=OFF
export TRADING_MODE=paper

export APCA_API_KEY_ID="..."
export APCA_API_SECRET_KEY="..."
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
```

### Install deps (once)

```bash
pip install -r functions/requirements.txt
```

### Single-command backtest (strategy + symbols + date range + timeframe)

Example: GammaScalper on 3 symbols, 5m bars:

```bash
python3 scripts/run_backtest.py \
  --strategy GammaScalper \
  --symbols SPY,QQQ,AAPL \
  --start 2025-12-01 \
  --end 2025-12-31 \
  --timeframe 5m \
  --initial-capital 100000 \
  --strategy-config-json '{"threshold":0.15,"gex_positive_multiplier":0.5,"gex_negative_multiplier":1.5}'
```

Supported timeframes: `1m`, `5m`, `15m`

### Where results are written

Each run writes a new timestamped directory:

- `audit_artifacts/backtests/<run_ts_utc>/summary.json`
- `audit_artifacts/backtests/<run_ts_utc>/results_<SYMBOL>.json`

### What to check (“ready for tomorrow”)

- **Preflight passes**: the command prints nothing like `PREFLIGHT_FAILED`
- **Summary exists**: `audit_artifacts/backtests/<run_ts_utc>/summary.json`
- **Metrics present** in `summary.json` per symbol:
  - `pnl`
  - `max_drawdown`
  - `total_trades`

