from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import yaml

from .schema import StrategyContract


def _repo_root() -> Path:
    # /workspace/backend/vnext/strategy_contracts/*.py -> parents[3] == /workspace
    return Path(__file__).resolve().parents[3]


def get_contract_dir() -> Path:
    """
    Resolve the strategy contract directory.

    Defaults to `configs/strategies/contracts` at repo root.
    """
    raw = os.getenv("STRATEGY_CONTRACT_DIR") or "configs/strategies/contracts"
    p = Path(raw)
    if not p.is_absolute():
        p = _repo_root() / p
    return p


def _candidate_paths(contract_dir: Path, strategy_id: str) -> list[Path]:
    sid = (strategy_id or "").strip()
    if not sid:
        return []
    return [
        contract_dir / f"{sid}.yaml",
        contract_dir / f"{sid}.yml",
        contract_dir / f"{sid}.json",
    ]


def _read_mapping(p: Path) -> dict[str, Any]:
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        d = json.loads(raw) if raw.strip() else {}
    else:
        d = yaml.safe_load(raw) if raw.strip() else {}
    if not isinstance(d, dict):
        raise ValueError(f"contract file must be a mapping: {p}")
    return d


def load_strategy_contract(strategy_id: str, *, contract_dir: Optional[Path] = None) -> StrategyContract:
    """
    Load a strategy contract from the contract directory.

    Contract files are resolved as:
    - <dir>/<strategy_id>.yaml
    - <dir>/<strategy_id>.yml
    - <dir>/<strategy_id>.json
    """
    sid = (strategy_id or "").strip()
    if not sid:
        raise ValueError("strategy_id is required")

    cdir = contract_dir or get_contract_dir()
    for p in _candidate_paths(cdir, sid):
        if not p.exists():
            continue
        d = _read_mapping(p)
        # Fail-closed: contract identity must match the filename strategy_id.
        if "strategy_id" not in d:
            d["strategy_id"] = sid
        return StrategyContract.model_validate(d)

    raise FileNotFoundError(
        f"strategy contract not found for '{sid}' in {str(cdir)} (expected .yaml/.yml/.json)"
    )

