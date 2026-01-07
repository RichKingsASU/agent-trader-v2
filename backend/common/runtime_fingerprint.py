from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_did_log = False


def log_runtime_fingerprint(*, service: str) -> None:
    """
    Emit a single startup log record that identifies what the container is running.

    Constraints:
    - stdlib-only (safe to import before other deps)
    - logging/printing only (no behavior changes)
    - idempotent within the process (logs once)
    """
    global _did_log
    with _lock:
        if _did_log:
            return
        _did_log = True

    agent_mode = os.getenv("AGENT_MODE") or "unknown"
    git_sha = os.getenv("GIT_SHA") or "unknown"
    image_tag = os.getenv("IMAGE_TAG") or "unknown"

    msg = (
        "RUNTIME_FINGERPRINT:\n"
        f"  service={service}\n"
        f"  agent_mode={agent_mode}\n"
        "  execution_enabled=false\n"
        f"  git_sha={git_sha}\n"
        f"  image_tag={image_tag}"
    )

    try:
        print(msg, flush=True)
    except Exception:
        # Never fail container startup due to fingerprint logging.
        pass

