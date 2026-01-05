"""Options window ingest Cloud Run Job entrypoint.

This is a thin wrapper around `backend.streams.alpaca_option_window_ingest`.
Deploy with:
  --command "python" --args "-m" --args "backend.jobs.options_window"
"""

from __future__ import annotations

from backend.streams.alpaca_option_window_ingest import main as _main


def main() -> int:
    return int(_main())


if __name__ == "__main__":
    raise SystemExit(main())

