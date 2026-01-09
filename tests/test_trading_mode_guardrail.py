from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestTradingModeGuardrail(unittest.TestCase):
    def test_ci_requires_trading_mode_paper(self) -> None:
        """
        CI safety guard: fail the build if TRADING_MODE is not explicitly paper.
        """
        if not (str(os.getenv("CI") or "").strip().lower() == "true" or os.getenv("GITHUB_ACTIONS")):
            raise unittest.SkipTest("CI-only guardrail")
        self.assertEqual(
            os.getenv("TRADING_MODE"),
            "paper",
            "CI must set TRADING_MODE=paper (paper-trading hard lock).",
        )

    def _run_guard_subprocess(self, *, trading_mode: str | None) -> subprocess.CompletedProcess[str]:
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["AGENT_MODE"] = "OFF"  # allowed by enforce_agent_mode_guard()
        if trading_mode is None:
            env.pop("TRADING_MODE", None)
        else:
            env["TRADING_MODE"] = trading_mode

        code = (
            "from backend.common.agent_mode_guard import enforce_agent_mode_guard\n"
            "enforce_agent_mode_guard()\n"
            "print('ok')\n"
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
        )

    def test_startup_refuses_missing_trading_mode(self) -> None:
        p = self._run_guard_subprocess(trading_mode=None)
        self.assertNotEqual(p.returncode, 0)
        combined = (p.stdout or "") + "\n" + (p.stderr or "")
        self.assertIn("TRADING_MODE", combined)
        self.assertIn("paper", combined)

    def test_startup_refuses_non_paper_trading_mode(self) -> None:
        p = self._run_guard_subprocess(trading_mode="live")
        self.assertNotEqual(p.returncode, 0)
        combined = (p.stdout or "") + "\n" + (p.stderr or "")
        self.assertIn("TRADING_MODE must be 'paper'", combined)

