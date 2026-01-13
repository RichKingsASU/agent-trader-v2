#!/usr/bin/env python3
"""
Canonical backtest runner (paper-only).

Supports:
- strategy name (GammaScalper, SectorRotation, ExampleStrategy, ...)
- symbol list (comma-separated)
- start/end date (YYYY-MM-DD)
- timeframe (1m/5m/15m)

Writes:
  audit_artifacts/backtests/<run_ts>/summary.json
  audit_artifacts/backtests/<run_ts>/results_<SYMBOL>.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.common.preflight import preflight_or_exit


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_functions_to_syspath() -> None:
    functions_dir = _repo_root() / "functions"
    sys.path.insert(0, str(functions_dir))


def _utc_run_ts() -> str:
    # Stable, filename-safe ISO-ish timestamp.
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_symbols(raw: str) -> list[str]:
    syms = [s.strip().upper() for s in (raw or "").split(",") if s.strip()]
    if not syms:
        raise ValueError("symbols list is empty")
    return syms


def _load_strategy_class(strategy_name: str):
    """
    Minimal dynamic loader for functions/strategies/*.py without relying on the
    unfinished StrategyLoader utilities.
    """
    strategy_name = str(strategy_name).strip()
    if not strategy_name:
        raise ValueError("--strategy is required")

    # Strategy modules live under "strategies" (functions/strategies) once
    # functions/ is added to sys.path.
    candidates = [
        "strategies.gamma_scalper",
        "strategies.sector_rotation",
        "strategies.example_strategy",
    ]
    for mod_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        cls = getattr(mod, strategy_name, None)
        if cls is not None:
            return cls

    raise ValueError(
        f"Unknown strategy {strategy_name!r}. "
        "Known (tonight): GammaScalper, SectorRotation, ExampleStrategy."
    )


def _instantiate_strategy(strategy_name: str, strategy_config: dict[str, Any]):
    cls = _load_strategy_class(strategy_name)
    try:
        return cls(config=strategy_config)
    except TypeError:
        # Some strategies may accept no args.
        return cls()


@dataclass(frozen=True)
class RunSummary:
    run_ts_utc: str
    strategy: str
    symbols: list[str]
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    per_symbol: dict[str, dict[str, Any]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paper-only backtests.")
    parser.add_argument("--strategy", required=True, help="Strategy class name (e.g., GammaScalper)")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. SPY,QQQ")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--timeframe", default="1m", choices=["1m", "5m", "15m"], help="Bar timeframe")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument(
        "--strategy-config-json",
        default="{}",
        help="JSON object for strategy config (default: '{}')",
    )
    args = parser.parse_args()

    # Hard guardrails + env validation.
    preflight_or_exit(extra_required_env=())

    _add_functions_to_syspath()

    try:
        strategy_cfg = json.loads(args.strategy_config_json or "{}")
        if not isinstance(strategy_cfg, dict):
            raise ValueError("strategy config must be a JSON object")
    except Exception as e:
        raise SystemExit(f"Invalid --strategy-config-json: {e}")

    symbols = _parse_symbols(args.symbols)
    run_ts = _utc_run_ts()

    out_dir = _repo_root() / "audit_artifacts" / "backtests" / run_ts
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import backtester after sys.path setup.
    from backtester import Backtester  # type: ignore  # noqa: WPS433

    per_symbol: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        strategy = _instantiate_strategy(args.strategy, strategy_cfg)
        bt = Backtester(
            strategy=strategy,
            symbol=sym,
            start_date=args.start,
            end_date=args.end,
            timeframe=args.timeframe,
            initial_capital=float(args.initial_capital),
        )
        results = bt.run()

        # Persist full results per symbol (useful for debugging).
        results_path = out_dir / f"results_{sym}.json"
        results_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")

        m = results.get("metrics") or {}
        per_symbol[sym] = {
            "final_equity": m.get("final_equity"),
            "pnl": (m.get("final_equity") - m.get("initial_capital")) if m.get("final_equity") is not None else None,
            "max_drawdown": m.get("max_drawdown"),
            "total_trades": m.get("total_trades"),
            "result_file": str(results_path.relative_to(_repo_root())),
        }

    summary = RunSummary(
        run_ts_utc=run_ts,
        strategy=str(args.strategy),
        symbols=symbols,
        timeframe=str(args.timeframe),
        start_date=str(args.start),
        end_date=str(args.end),
        initial_capital=float(args.initial_capital),
        per_symbol=per_symbol,
    )
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(asdict(summary), indent=2, default=str) + "\n", encoding="utf-8")

    print(f"Wrote backtest artifacts to: {out_dir}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

