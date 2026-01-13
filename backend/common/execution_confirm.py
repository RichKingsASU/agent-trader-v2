from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any


class ExecutionConfirmTokenError(RuntimeError):
    """
    Raised when a live-execution confirmation token is missing/incorrect.

    Design intent:
    - Present in code now, but only enforced if/when a future live trading mode is enabled.
    - Provides a second, explicit, operator-supplied confirmation beyond config flags.
    """


_B64_ALPHABET_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_JTI_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    # urlsafe_b64decode requires proper padding.
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _replay_dir() -> str:
    # A cross-process, local-only replay store. Tests set this to a temp dir.
    return str(os.getenv("EXECUTION_CONFIRM_REPLAY_DIR") or "/tmp/agenttrader_exec_confirm_used_tokens").strip()


def _consume_once(*, jti: str, exp: int) -> None:
    """
    Enforce single-use tokens across processes by atomically creating a marker file.
    """
    if not _JTI_RE.match(jti):
        raise ExecutionConfirmTokenError("Refusing live execution: invalid confirmation token id (jti).")

    d = _replay_dir()
    if not d:
        raise ExecutionConfirmTokenError("Refusing live execution: replay store misconfigured (empty dir).")

    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        raise ExecutionConfirmTokenError(f"Refusing live execution: cannot initialize replay store: {e}") from e

    marker = os.path.join(d, jti)
    payload = json.dumps({"jti": jti, "exp": int(exp)}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        # Atomic across processes: succeeds once, fails thereafter.
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    except FileExistsError as e:
        raise ExecutionConfirmTokenError(
            "Refusing live execution: confirmation token replay detected (token already used)."
        ) from e
    except Exception as e:
        raise ExecutionConfirmTokenError(f"Refusing live execution: cannot write replay marker: {e}") from e


def _parse_and_verify_v1(
    *,
    secret: str,
    token: str,
    expected_scope: str,
    now_epoch_s: int,
) -> dict[str, Any]:
    parts = [p for p in str(token).split(".") if p != ""]
    if len(parts) != 3 or parts[0] != "v1":
        raise ExecutionConfirmTokenError(
            "Refusing live execution: invalid confirmation token format (expected v1.<payload>.<sig>)."
        )
    _, payload_b64, sig_b64 = parts
    if (not _B64_ALPHABET_RE.match(payload_b64)) or (not _B64_ALPHABET_RE.match(sig_b64)):
        raise ExecutionConfirmTokenError("Refusing live execution: invalid confirmation token encoding.")

    signing_input = f"v1.{payload_b64}".encode("utf-8")
    expected_sig = _b64url_encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not _constant_time_eq(expected_sig, sig_b64):
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token signature invalid.")

    try:
        payload_raw = _b64url_decode(payload_b64)
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception as e:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token payload invalid.") from e

    if not isinstance(payload, dict):
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token payload invalid.")

    scope = str(payload.get("scope") or "").strip()
    if not scope:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token missing scope.")
    if scope != expected_scope:
        raise ExecutionConfirmTokenError(
            f"Refusing live execution: confirmation token scope mismatch (expected {expected_scope!r}, got {scope!r})."
        )

    try:
        exp = int(payload.get("exp"))
    except Exception as e:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token missing/invalid exp.") from e
    if now_epoch_s >= exp:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token expired.")

    jti = str(payload.get("jti") or "").strip()
    if not jti:
        raise ExecutionConfirmTokenError("Refusing live execution: confirmation token missing jti.")

    return {"jti": jti, "exp": exp, "scope": scope}


def require_confirm_token_for_live_execution(
    *,
    provided_token: str | None,
    expected_scope: str = "execution.execute_intent",
    consume: bool = True,
    now_epoch_s: int | None = None,
) -> None:
    """
    Fail-closed unless the provided token matches the expected runtime token.

    Contract:
    - A signing secret is read from EXECUTION_CONFIRM_TOKEN (fail-closed if missing/empty).
    - Caller provides a token in header X-Exec-Confirm-Token with format: v1.<payload_b64url>.<sig_b64url>
    - Token payload MUST include: jti, scope, exp
    - Scope MUST match expected_scope.
    - Token MUST be unexpired.
    - Token MUST be single-use (replay across executions/processes is refused).
    """
    expected = str(os.getenv("EXECUTION_CONFIRM_TOKEN") or "").strip()
    if not expected:
        raise ExecutionConfirmTokenError(
            "Refusing live execution: EXECUTION_CONFIRM_TOKEN is missing/empty "
            "(confirmation token gate is fail-closed)."
        )
    provided = str(provided_token or "").strip()
    if not provided:
        raise ExecutionConfirmTokenError(
            "Refusing live execution: missing confirmation token "
            "(provide X-Exec-Confirm-Token)."
        )
    now_s = int(time.time()) if now_epoch_s is None else int(now_epoch_s)
    parsed = _parse_and_verify_v1(secret=expected, token=provided, expected_scope=expected_scope, now_epoch_s=now_s)
    if consume:
        _consume_once(jti=str(parsed["jti"]), exp=int(parsed["exp"]))

