from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def test_cloudrun_ingestor_sigterm_exits_under_10s() -> None:
    """
    Acceptance: Local test proves shutdown completes <10s.

    This runs a lightweight harness that imports `cloudrun_ingestor.main`,
    waits, then we SIGTERM it and assert it exits promptly.
    """

    env = dict(os.environ)
    # Ensure the repo root is on sys.path for `python -m ...`.
    env["PYTHONPATH"] = env.get("PYTHONPATH", "")
    if "/workspace" not in env["PYTHONPATH"].split(":"):
        env["PYTHONPATH"] = ("/workspace:" + env["PYTHONPATH"]).strip(":")

    p = subprocess.Popen(
        [sys.executable, "-m", "cloudrun_ingestor.shutdown_smoke"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        # Give it a brief moment to import + block.
        time.sleep(0.75)
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            p.kill()
            raise AssertionError("process did not exit within 10s of SIGTERM")

        elapsed = time.monotonic() - t0
        assert elapsed < 10.0

        out, err = p.communicate(timeout=2.0)
        # Exit code is allowed to be 0 (harness main return), or a signal-style code.
        assert p.returncode in (0, 128 + signal.SIGTERM, 128 + signal.SIGINT)
        assert "shutdown_smoke.ready" in out
        # No hard assertion on stderr; keep visibility if it fails.
        _ = err
    finally:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass

