from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Iterable

from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.env import get_alpaca_api_base_url, get_alpaca_key_id, get_alpaca_secret_key


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    missing: list[str]
    errors: list[str]


def _is_set(name: str) -> bool:
    v = os.getenv(name)
    return v is not None and str(v).strip() != ""


def run_paper_preflight(*, extra_required_env: Iterable[str] = ()) -> PreflightResult:
    """
    Fast-failing startup preflight for any backtest/seed scripts.

    Hard requirements:
    - AGENT_MODE must be explicitly set and must not allow execution
    - TRADING_MODE must be explicitly set to "paper"
    - Alpaca env vars must be present and must pass paper-host assertions:
      - APCA_API_KEY_ID
      - APCA_API_SECRET_KEY
      - APCA_API_BASE_URL (must be paper host)

    Additional required env vars can be passed via extra_required_env.
    """
    missing: list[str] = []
    errors: list[str] = []

    # Always enforce repo-wide guardrails first.
    # This is intentionally non-bypassable by these scripts.
    try:
        enforce_agent_mode_guard()
    except SystemExit as e:
        errors.append(f"agent_mode_guard_failed exit_code={getattr(e, 'code', None)}")
    except Exception as e:
        errors.append(f"agent_mode_guard_failed error={e}")

    # Validate Alpaca paper-only env contract.
    # These functions enforce the paper host assertion and raise on violation.
    try:
        _ = get_alpaca_key_id(required=True)
    except Exception as e:
        missing.append("APCA_API_KEY_ID")
        errors.append(str(e))

    try:
        _ = get_alpaca_secret_key(required=True)
    except Exception as e:
        missing.append("APCA_API_SECRET_KEY")
        errors.append(str(e))

    try:
        _ = get_alpaca_api_base_url(required=True)
    except Exception as e:
        missing.append("APCA_API_BASE_URL")
        errors.append(str(e))

    for name in extra_required_env:
        if not _is_set(str(name)):
            missing.append(str(name))

    ok = (not missing) and (not errors)
    return PreflightResult(ok=ok, missing=sorted(set(missing)), errors=errors)


def preflight_or_exit(*, extra_required_env: Iterable[str] = (), exit_code: int = 2) -> None:
    """
    Run preflight, print a human-friendly report, and exit nonzero on failure.
    """
    r = run_paper_preflight(extra_required_env=extra_required_env)
    if r.ok:
        return

    # Stable output format for CI / operators.
    sys.stderr.write("PREFLIGHT_FAILED\n")
    if r.missing:
        sys.stderr.write("Missing env vars:\n")
        for k in r.missing:
            sys.stderr.write(f" - {k}\n")
    if r.errors:
        sys.stderr.write("Errors:\n")
        for msg in r.errors:
            sys.stderr.write(f" - {msg}\n")
    sys.stderr.flush()
    raise SystemExit(exit_code)

