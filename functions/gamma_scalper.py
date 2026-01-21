"""
Deprecated execution entrypoint for the Gamma Scalper.

This file previously contained a broker-execution-capable loop. As part of the
repo safety posture, execution-capable entrypoints must live under `scripts/`
and be protected by `scripts/lib/exec_guard.py` MUST_LOCK policy + additional
runtime gates.

Use:
  `scripts/run_gamma_scalper.py`
"""


def main() -> None:
    raise SystemExit(
        "REFUSED: functions/gamma_scalper.py is deprecated.\n"
        "Run the guarded entrypoint instead: scripts/run_gamma_scalper.py"
    )


if __name__ == "__main__":
    main()
