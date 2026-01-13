from __future__ import annotations

import os
import sys


def is_local_execution() -> bool:
    """
    Heuristic: treat execution as "local" when either:
    - ENV=local, OR
    - we're not on a managed GCP runtime (no K_SERVICE, no CLOUD_RUN_JOB, and no GAE_* env vars).
    """
    if (os.getenv("ENV") or "").strip().lower() == "local":
        return True

    if (os.getenv("K_SERVICE") or "").strip():
        return False
    if (os.getenv("CLOUD_RUN_JOB") or "").strip():
        return False
    for k in os.environ.keys():
        if str(k).startswith("GAE_"):
            return False

    return True


def require_firestore_emulator_or_allow_prod(*, caller: str) -> None:
    """
    Safety guard: fail-closed locally unless the Firestore emulator is configured.

    Local execution MUST set FIRESTORE_EMULATOR_HOST, unless explicitly overridden with:
      ALLOW_PROD_FIRESTORE=1
    """
    if not is_local_execution():
        return
    if (os.getenv("FIRESTORE_EMULATOR_HOST") or "").strip():
        return
    if (os.getenv("ALLOW_PROD_FIRESTORE") or "").strip() == "1":
        return

    sys.stderr.write(
        "\n".join(
            [
                "ERROR: Refusing to use production Firestore from local execution.",
                f"caller={caller}",
                "",
                "This repo fails closed locally unless the Firestore emulator is configured.",
                "Fix:",
                "  - Set FIRESTORE_EMULATOR_HOST (example: '127.0.0.1:8080'), OR",
                "  - Intentionally override with ALLOW_PROD_FIRESTORE=1 (DANGEROUS).",
                "",
            ]
        )
        + "\n"
    )
    raise SystemExit(2)

