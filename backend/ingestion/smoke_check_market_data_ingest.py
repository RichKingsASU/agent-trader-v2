from __future__ import annotations

import asyncio
import os

from backend.ingestion.market_data_ingest import MarketDataIngestor, load_config_from_env, log_json


async def _amain() -> int:
    cfg = load_config_from_env()

    # Force a bounded run for smoke checks.
    cfg.stop_after_seconds = 60.0

    # Deterministic Alpaca auth smoke tests (startup gate).
    if (
        (not cfg.dry_run)
        and os.getenv("SKIP_ALPACA_AUTH_SMOKE_TESTS", "").strip().lower() not in ("1", "true", "yes", "y")
    ):
        from backend.streams.alpaca_auth_smoke import run_alpaca_auth_smoke_tests_async  # noqa: WPS433

        feed = getattr(cfg.feed, "value", None) or "iex"
        timeout_s = float(os.getenv("ALPACA_AUTH_SMOKE_TIMEOUT_S", "5"))
        await run_alpaca_auth_smoke_tests_async(feed=str(feed), timeout_s=timeout_s)

    ingestor = MarketDataIngestor(cfg)
    stats = await ingestor.run()

    # Quote writes go to live_quotes/{symbol}; heartbeats go to ops/market_ingest.
    writes_ok = stats.firestore_writes_ok + stats.heartbeat_writes_ok
    writes_err = stats.firestore_writes_err + stats.heartbeat_writes_err

    if cfg.dry_run:
        # DRY_RUN contract: no Firestore writes, but we should still observe at least one
        # "would-write" action (tracked via stats + structured logs).
        if writes_ok >= 1:
            print(
                "PASS: DRY_RUN observed write intents "
                f"(intents={writes_ok}, quote_events={stats.quote_events})."
            )
            return 0
        print(f"FAIL: DRY_RUN observed zero write intents (quote_events={stats.quote_events}).")
        return 1

    # Non-DRY_RUN: at least one successful Firestore write occurred (quote and/or heartbeat).
    if writes_ok >= 1:
        print(f"PASS: Firestore writes observed (ok={writes_ok}, err={writes_err}).")
        return 0

    print(
        "FAIL: No successful Firestore writes observed in 60s "
        f"(ok={writes_ok}, err={writes_err}, quote_events={stats.quote_events})."
    )
    return 1


def main() -> None:
    # Emit one structured log line so Cloud Run logs show start/stop.
    log_json("smoke_start", stop_after_seconds=60)
    rc = asyncio.run(_amain())
    log_json("smoke_end", status="ok" if rc == 0 else "error", exit_code=rc)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()

