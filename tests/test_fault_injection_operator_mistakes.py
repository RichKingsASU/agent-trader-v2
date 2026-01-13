from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_python_snippet(*, code: str, env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    """
    Run a Python snippet in a clean subprocess to avoid import/env cross-test leakage.
    """
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "name,code,env_overrides,expected_rc,expected_substrings",
    [
        (
            "AGENT_MODE=LIVE with TRADING_MODE=paper must fail (invalid agent mode)",
            # NOTE: run via startup guard to ensure we fail-fast with SystemExit.
            "from backend.common.agent_mode_guard import enforce_agent_mode_guard\n"
            "enforce_agent_mode_guard()\n"
            "print('SHOULD_NOT_REACH')\n",
            {"AGENT_MODE": "LIVE", "TRADING_MODE": "paper"},
            1,
            ["AGENT_MODE", "not allowed"],
        ),
        (
            "AGENT_MODE=paper with TRADING_MODE=live must fail (paper-trading hard lock)",
            "from backend.common.agent_mode_guard import enforce_agent_mode_guard\n"
            "enforce_agent_mode_guard()\n"
            "print('SHOULD_NOT_REACH')\n",
            {"AGENT_MODE": "paper", "TRADING_MODE": "live"},
            13,
            ["TRADING_MODE must be 'paper'", "paper-trading hard lock"],
        ),
        (
            "TRADING_MODE=live with missing EXECUTION_CONFIRM_TOKEN must fail (fail-closed token gate)",
            # Use the explicit token gate directly: this is the intended secondary guard if/when live is enabled.
            "import sys\n"
            "from backend.common.execution_confirm import require_confirm_token_for_live_execution, ExecutionConfirmTokenError\n"
            "try:\n"
            "    require_confirm_token_for_live_execution(provided_token='any')\n"
            "    print('SHOULD_NOT_REACH')\n"
            "    sys.exit(0)\n"
            "except ExecutionConfirmTokenError as e:\n"
            "    sys.stderr.write(f'FATAL:{e}\\n')\n"
            "    raise SystemExit(21)\n",
            {"TRADING_MODE": "live", "EXECUTION_CONFIRM_TOKEN": None},
            21,
            ["FATAL:", "EXECUTION_CONFIRM_TOKEN is missing/empty", "fail-closed"],
        ),
        (
            "Valid token + wrong APCA_API_BASE_URL must fail (no silent fallback to aliases)",
            # Ensure the confirm-token gate passes, then ensure APCA_API_BASE_URL is rejected even if an alias is paper.
            "import sys\n"
            "from backend.common.execution_confirm import require_confirm_token_for_live_execution\n"
            "from backend.common.env import get_alpaca_api_base_url\n"
            "try:\n"
            "    require_confirm_token_for_live_execution(provided_token='tok')\n"
            "    _ = get_alpaca_api_base_url(required=True)\n"
            "    print('SHOULD_NOT_REACH')\n"
            "    sys.exit(0)\n"
            "except Exception as e:\n"
            "    sys.stderr.write(f'FATAL:{type(e).__name__}:{e}\\n')\n"
            "    raise SystemExit(22)\n",
            {
                "TRADING_MODE": "live",
                "EXECUTION_CONFIRM_TOKEN": "tok",
                # Operator mistake: wrong canonical env var.
                "APCA_API_BASE_URL": "https://api.alpaca.markets",
                # Ensure no silent fallback to aliases occurs.
                "ALPACA_TRADING_HOST": "https://paper-api.alpaca.markets",
            },
            22,
            ["FATAL:", "REFUSED:", "Alpaca", "forbidden"],
        ),
        (
            "Live URL + paper mode must fail (paper host enforcement)",
            "import sys\n"
            "from backend.common.env import get_alpaca_api_base_url\n"
            "try:\n"
            "    _ = get_alpaca_api_base_url(required=True)\n"
            "    print('SHOULD_NOT_REACH')\n"
            "    sys.exit(0)\n"
            "except Exception as e:\n"
            "    sys.stderr.write(f'FATAL:{type(e).__name__}:{e}\\n')\n"
            "    raise SystemExit(23)\n",
            {"TRADING_MODE": "paper", "APCA_API_BASE_URL": "https://api.alpaca.markets"},
            23,
            ["FATAL:", "live Alpaca trading host is forbidden"],
        ),
    ],
)
def test_fault_injection_operator_mistakes_fail_closed(
    name: str,
    code: str,
    env_overrides: dict[str, str | None],
    expected_rc: int,
    expected_substrings: list[str],
) -> None:
    p = _run_python_snippet(code=code, env_overrides=env_overrides)
    combined = (p.stdout or "") + "\n" + (p.stderr or "")

    # Deterministic fatal error: must fail and must not continue.
    assert p.returncode == expected_rc, f"{name}\nstdout/stderr:\n{combined}"
    assert "SHOULD_NOT_REACH" not in combined, f"{name}\nstdout/stderr:\n{combined}"

    # No silent fallback: assert we get explicit, greppable error text.
    for s in expected_substrings:
        assert s in combined, f"{name}\nmissing substring: {s!r}\nstdout/stderr:\n{combined}"

