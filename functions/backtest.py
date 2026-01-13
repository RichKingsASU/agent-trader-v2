"""
Single-entry backtest runner.

Provides a single command-style function:
  backtest(strategy, symbol, start_date, end_date)

This is designed for SAFE options-strategy simulation:
- No broker execution (historical bars only)
- Options inputs are modeled via proxy Greeks in the backtester (unless extended)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


def _json_safe(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x) for x in v]
    # Decimal/datetime, etc
    try:
        import decimal

        if isinstance(v, decimal.Decimal):
            return float(v)
    except Exception:
        pass
    try:
        if isinstance(v, datetime):
            return v.isoformat()
    except Exception:
        pass
    return str(v)


def _default_artifacts_root() -> Path:
    # repo root / audit_artifacts / backtests
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    return repo_root / "audit_artifacts" / "backtests"


def backtest(
    strategy: Union[str, Any],
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    strategy_config: Optional[Dict[str, Any]] = None,
    start_capital: float = 100000.0,
    slippage_bps: int = 1,
    regime: Optional[str] = None,
    alpaca_api_key: Optional[str] = None,
    alpaca_secret_key: Optional[str] = None,
    artifacts_root: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Run a historical backtest and write metrics/results artifacts to disk.

    Args:
        strategy: Strategy instance or a strategy class name (e.g., "GammaScalper")
        symbol: Underlying symbol (e.g., "SPY")
        start_date: YYYY-MM-DD (or ISO datetime)
        end_date: YYYY-MM-DD (or ISO datetime)

    Returns:
        Dict containing results, metrics, and artifact paths.
    """
    # Import locally: functions/ is not a package in many contexts.
    from strategies.backtester import Backtester, BacktestConfig  # type: ignore
    from strategies.metrics_calculator import MetricsCalculator  # type: ignore

    if isinstance(strategy, str):
        from strategies.loader import instantiate_strategy  # type: ignore

        strategy_obj = instantiate_strategy(
            strategy_name=strategy,
            name=f"{strategy}_backtest",
            config=strategy_config or {},
        )
        strategy_name = strategy
    else:
        strategy_obj = strategy
        strategy_name = getattr(strategy_obj, "get_strategy_name", lambda: strategy_obj.__class__.__name__)()

    key = alpaca_api_key or os.getenv("APCA_API_KEY_ID")
    secret = alpaca_secret_key or os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError("Alpaca API credentials required (APCA_API_KEY_ID / APCA_API_SECRET_KEY).")

    cfg = BacktestConfig(
        symbol=str(symbol).upper(),
        start_capital=__import__("decimal").Decimal(str(start_capital)),
        lookback_days=1,  # ignored when start/end provided
        start_date=str(start_date),
        end_date=str(end_date),
        slippage_bps=int(slippage_bps),
    )

    bt = Backtester(
        strategy=strategy_obj,
        config=cfg,
        alpaca_api_key=key,
        alpaca_secret_key=secret,
    )
    results = bt.run(regime=regime)

    metrics_calc = MetricsCalculator()
    equity_curve_tuples = [
        (datetime.fromisoformat(p["timestamp"]), __import__("decimal").Decimal(str(p["equity"])))
        for p in results["equity_curve"]
    ]

    unrealized = float(results.get("unrealized_pnl", 0.0))
    metrics = metrics_calc.calculate_all_metrics(
        equity_curve=equity_curve_tuples,
        trades=results["trades"],
        start_capital=cfg.start_capital,
        unrealized_pnl_dollars=unrealized,
    )

    # Artifact writing
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{strategy_name}_{cfg.symbol}_{start_date}_{end_date}_{ts}".replace(" ", "_")
    root = Path(artifacts_root) if artifacts_root is not None else _default_artifacts_root()
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = run_dir / "metrics.json"
    results_path = run_dir / "results.json"
    config_path = run_dir / "config.json"

    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(metrics), f, indent=2)
    with results_path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(results), f, indent=2)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(asdict(cfg)), f, indent=2)

    return {
        "strategy": strategy_name,
        "symbol": cfg.symbol,
        "date_range": {"start": str(start_date), "end": str(end_date)},
        "results": results,
        "metrics": metrics,
        "artifacts": {
            "run_dir": str(run_dir),
            "metrics_path": str(metrics_path),
            "results_path": str(results_path),
            "config_path": str(config_path),
        },
    }

