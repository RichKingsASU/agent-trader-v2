from __future__ import annotations

"""
Local shutdown smoke harness for `cloudrun_ingestor`.

Purpose:
- Provide a deterministic local way to verify SIGTERM exits within Cloud Run's 10s window.
- Used by automated tests to prove the shutdown path is bounded.

Run:
  python -m cloudrun_ingestor.shutdown_smoke

Then from another shell:
  kill -TERM <pid>
"""

import os
import sys
import time


def _ensure_env(name: str, default: str) -> None:
    if (os.getenv(name) or "").strip():
        return
    os.environ[name] = default


def main() -> int:
    # `cloudrun_ingestor.main` validates these at import time.
    _ensure_env("GCP_PROJECT", "local-test")
    _ensure_env("SYSTEM_EVENTS_TOPIC", "system.events")
    _ensure_env("MARKET_TICKS_TOPIC", "market.ticks")
    _ensure_env("MARKET_BARS_1M_TOPIC", "market.bars.1m")
    _ensure_env("TRADE_SIGNALS_TOPIC", "trade.signals")
    _ensure_env("INGEST_FLAG_SECRET_ID", "ingest-flag")

    started = time.monotonic()
    try:
        from cloudrun_ingestor import main as ingestor_main  # noqa: WPS433
    except Exception as e:
        sys.stderr.write(f"shutdown_smoke.import_failed: {type(e).__name__}: {e}\n")
        sys.stderr.flush()
        return 1

    sys.stdout.write("shutdown_smoke.ready\n")
    sys.stdout.flush()

    # Block until shutdown is requested.
    try:
        ingestor_main.SHUTDOWN_FLAG.wait()
    except KeyboardInterrupt:
        pass
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        sys.stdout.write(f"shutdown_smoke.exiting elapsed_ms={elapsed_ms}\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

