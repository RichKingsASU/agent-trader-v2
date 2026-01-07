from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import random
from typing import Any

from research.experiments.contract import ExperimentSpec


DEFAULT_SPEC = ExperimentSpec(
    experiment_id="gamma_signal_sanity",
    name="Gamma Signal Sanity (Synthetic)",
    description=(
        "Synthetic price series + simple moving-average indicator sanity check. "
        "Designed to be deterministic and offline-safe."
    ),
    input_dataset="research/datasets/synthetic_prices/v1",
    parameters={
        "n_days": 252,
        "start_price": 100.0,
        "drift": 0.0002,
        "vol": 0.01,
        "ma_window": 20,
    },
    metrics=["sharpe_like", "hit_rate", "max_drawdown"],
    output_dir="",  # injected by runner
    seed=42,
)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _moving_average(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for x in equity:
        if x > peak:
            peak = x
        dd = (peak - x) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return mdd


def run(spec: ExperimentSpec, output_dir: Path) -> dict[str, Any]:
    """
    Deterministic synthetic experiment:
      - generate daily returns via seeded RNG
      - build price series
      - compute moving-average “trend” signal
      - compute simple metrics + write artifacts
    """
    params = spec.parameters
    n_days = int(params.get("n_days", 252))
    start_price = float(params.get("start_price", 100.0))
    drift = float(params.get("drift", 0.0))
    vol = float(params.get("vol", 0.01))
    ma_window = int(params.get("ma_window", 20))

    rng = random.Random(int(spec.seed))

    # Daily log returns (Gaussian) => prices via exp(cumsum)
    rets: list[float] = []
    prices: list[float] = []
    log_p = math.log(start_price)
    for _ in range(n_days):
        r = drift + vol * rng.gauss(0.0, 1.0)
        rets.append(r)
        log_p += r
        prices.append(math.exp(log_p))

    ma = _moving_average(prices, ma_window)
    # Signal: +1 if above MA else -1; use previous-day signal to avoid lookahead
    raw_sig: list[int] = []
    for i in range(n_days):
        if ma[i] is None:
            raw_sig.append(0)
        else:
            raw_sig.append(1 if prices[i] > float(ma[i]) else -1)
    sig_prev = [0] + raw_sig[:-1]

    strat_rets = [sig_prev[i] * rets[i] for i in range(n_days)]
    mu = _mean(strat_rets)
    sd = _std(strat_rets)
    sharpe_like = (mu / sd * math.sqrt(252.0)) if sd > 0 else 0.0
    hit_rate = sum(1 for x in strat_rets if x > 0) / n_days if n_days else 0.0

    equity = [1.0]
    for r in strat_rets:
        equity.append(equity[-1] * math.exp(r))
    max_dd = _max_drawdown(equity)

    artifacts_dir = output_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Artifact 1: lightweight JSON summary + small samples (kept small for git/CI)
    summary = {
        "n_days": n_days,
        "parameters": {
            "start_price": start_price,
            "drift": drift,
            "vol": vol,
            "ma_window": ma_window,
        },
        "samples": {
            "prices_head": prices[:5],
            "prices_tail": prices[-5:],
            "signal_head": raw_sig[:10],
            "signal_tail": raw_sig[-10:],
        },
    }
    (artifacts_dir / "series_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    # Artifact 2: CSV equity curve (small enough; deterministic)
    with (artifacts_dir / "equity_curve.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "equity"])
        for i, v in enumerate(equity):
            w.writerow([i, f"{v:.10f}"])

    return {
        "experiment_id": spec.experiment_id,
        "metrics": {
            "sharpe_like": sharpe_like,
            "hit_rate": hit_rate,
            "max_drawdown": max_dd,
        },
    }

