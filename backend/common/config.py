from __future__ import annotations

"""
Minimal, side-effect-free configuration helpers.

This module is intentionally lightweight:
- Pure env parsing helpers (`env_str`, `env_int`, `env_csv`, ...)
- A single fail-fast entrypoint (`validate_or_exit`) used by service entrypoints
  to enforce required env presence without importing heavy dependencies.
"""

import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


TRUTHY = {"1", "true", "t", "yes", "y", "on"}
FALSY = {"0", "false", "f", "no", "n", "off"}


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    """
    Parse a bool-like value.

    Accepts:
    - bool
    - int/float (0 -> False, non-zero -> True)
    - strings in TRUTHY/FALSY sets
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if value is None:
        return bool(default)
    s = str(value).strip().lower()
    if not s:
        return bool(default)
    if s in TRUTHY:
        return True
    if s in FALSY:
        return False
    return bool(default)


def env_str(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default
    return str(v).strip()


def env_int(name: str, default: int | None = None, *, required: bool = False) -> int | None:
    v = env_str(name, None, required=required)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except Exception:
        if required:
            raise RuntimeError(f"Invalid int env var: {name}")
        return default


def env_float(name: str, default: float | None = None, *, required: bool = False) -> float | None:
    v = env_str(name, None, required=required)
    if v is None:
        return default
    try:
        return float(str(v).strip())
    except Exception:
        if required:
            raise RuntimeError(f"Invalid float env var: {name}")
        return default


def env_csv(
    name: str,
    default: Sequence[str] | None = None,
    *,
    required: bool = False,
    sep: str = ",",
) -> list[str]:
    v = env_str(name, None, required=required)
    if v is None:
        return list(default or [])
    items = [p.strip() for p in str(v).split(sep)]
    return [p for p in items if p]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:
    """
    Centralized startup env validation hook.

    Current behavior:
    - If `config/preflight.yaml` exists and contains `required_env_vars`, enforce those.
    - Otherwise, no-op (do not break local dev/test imports).
    """
    from backend.safety.startup_validation import validate_required_env_or_exit  # local import (keeps module lightweight)

    e = env or os.environ  # type: ignore[assignment]
    _ = service  # reserved for future service-specific contracts

    required: list[str] = []
    preflight = _repo_root() / "config" / "preflight.yaml"
    if preflight.exists():
        try:
            import yaml  # type: ignore
        except Exception:
            yaml = None  # type: ignore[assignment]
        if yaml is not None:
            try:
                obj = yaml.safe_load(preflight.read_text(encoding="utf-8")) or {}
                if isinstance(obj, dict):
                    xs = obj.get("required_env_vars") or []
                    if isinstance(xs, list):
                        required = [str(x).strip() for x in xs if str(x).strip()]
            except Exception:
                required = []

    if required:
        validate_required_env_or_exit(env=e, required=required, intent_type="config_validation_failed")

