from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from .models import StrategyConfig
from .validator import ValidationContext, validate_strategy_config, is_execution_allowed_stub

logger = logging.getLogger(__name__)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # /workspace/backend/strategies/registry/loader.py -> parents[3] == /workspace
    return Path(__file__).resolve().parents[3]


def _get_config_dir() -> Path:
    raw = os.getenv("STRATEGY_CONFIG_DIR") or "configs/strategies"
    p = Path(raw)
    if not p.is_absolute():
        p = _repo_root() / p
    return p


def _best_effort_git_sha() -> Optional[str]:
    for k in ("GIT_SHA", "COMMIT_SHA", "SHORT_SHA", "BUILD_SHA", "SOURCE_VERSION"):
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip()[:64]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_repo_root()),
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        return out[:64] if out else None
    except Exception:
        return None


def _load_symbol_allowlist(config_dir: Path) -> Optional[set[str]]:
    """
    If an allowlist exists, enforce it.

    Supported:
    - STRATEGY_SYMBOL_ALLOWLIST="SPY,IWM,QQQ"
    - <config_dir>/symbol_allowlist.txt (one symbol per line)
    """
    env = os.getenv("STRATEGY_SYMBOL_ALLOWLIST")
    if env and env.strip():
        return {s.strip() for s in env.split(",") if s.strip()}

    p = config_dir / "symbol_allowlist.txt"
    if not p.exists():
        return None
    try:
        rows = []
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            rows.append(s)
        return set(rows)
    except Exception:
        # Fail-safe: if allowlist exists but can't be read, treat as no allowlist
        # (caller can still choose to error by adding env allowlist).
        return None


def _iter_config_files(config_dir: Path) -> list[Path]:
    if not config_dir.exists():
        return []
    out: list[Path] = []
    for p in sorted(config_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".yaml", ".yml", ".json"}:
            out.append(p)
    return out


def _read_config_file(p: Path) -> dict[str, Any]:
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        return json.loads(raw) if raw.strip() else {}
    return yaml.safe_load(raw) if raw.strip() else {}


def _hash_registry(files: list[Path]) -> str:
    """
    Compute a stable registry hash based on raw file bytes.
    """
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode("utf-8"))
        h.update(b"\n")
        h.update(p.read_bytes())
        h.update(b"\n---\n")
    return h.hexdigest()


def _snapshot_path(config_dir: Path) -> Path:
    # Note: repo .gitignore ignores *.json globally; this snapshot stays local.
    return config_dir / ".strategy_config_registry_snapshot.json"


def _read_previous_snapshot(config_dir: Path) -> Optional[dict[str, Any]]:
    sp = _snapshot_path(config_dir)
    if not sp.exists():
        return None
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_snapshot(config_dir: Path, *, registry_hash: str) -> None:
    sp = _snapshot_path(config_dir)
    try:
        sp.write_text(
            json.dumps({"hash": registry_hash, "ts": _utc_ts()}, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        return


def load_all_configs() -> list[StrategyConfig]:
    """
    Load and validate all strategy configs from the registry directory.

    Raises on:
    - invalid configs
    - duplicate strategy_id
    """
    config_dir = _get_config_dir()
    files = _iter_config_files(config_dir)

    prev = _read_previous_snapshot(config_dir)
    new_hash = _hash_registry(files)
    if prev and prev.get("hash") and prev.get("hash") != new_hash:
        logger.info(
            "intent %s",
            json.dumps(
                {
                    "intent_type": "strategy_config_changed",
                    "ts": _utc_ts(),
                    "config_dir": str(config_dir),
                    "old_hash": prev.get("hash"),
                    "new_hash": new_hash,
                },
                separators=(",", ":"),
            ),
        )
    _write_snapshot(config_dir, registry_hash=new_hash)

    symbol_allowlist = _load_symbol_allowlist(config_dir)
    allow_execution = is_execution_allowed_stub()
    git_sha = _best_effort_git_sha()

    seen: dict[str, StrategyConfig] = {}
    out: list[StrategyConfig] = []

    for p in files:
        d = _read_config_file(p) or {}
        if not isinstance(d, dict):
            raise ValueError(f"config file must be a mapping: {p}")

        # If strategy_id omitted, infer from file stem (GitOps friendly).
        if not d.get("strategy_id"):
            d["strategy_id"] = p.stem

        cfg = StrategyConfig.model_validate(d)
        if git_sha:
            cfg.version.git_sha = git_sha

        cfg = validate_strategy_config(
            cfg, ctx=ValidationContext(symbol_allowlist=symbol_allowlist, allow_execution=allow_execution)
        )

        if cfg.strategy_id in seen:
            raise ValueError(f"duplicate strategy_id: {cfg.strategy_id}")
        seen[cfg.strategy_id] = cfg
        out.append(cfg)

        logger.info(
            "intent %s",
            json.dumps(
                {
                    "intent_type": "strategy_config_loaded",
                    "ts": _utc_ts(),
                    "strategy_id": cfg.strategy_id,
                    "version": {
                        "config_version": cfg.version.config_version,
                        "git_sha": cfg.version.git_sha,
                    },
                    "enabled": bool(cfg.enabled),
                    "mode": cfg.mode.value,
                    "requires_human_approval": bool(cfg.approvals.requires_human_approval),
                },
                separators=(",", ":"),
            ),
        )

    return out


def load_config(strategy_id: str) -> StrategyConfig:
    sid = (strategy_id or "").strip()
    if not sid:
        raise ValueError("strategy_id is required")
    rows = load_all_configs()
    for c in rows:
        if c.strategy_id == sid:
            return c
    raise KeyError(f"strategy_id not found: {sid}")

