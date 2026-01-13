from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from multiprocessing import Process, Queue

import pytest

from backend.common.execution_confirm import ExecutionConfirmTokenError, require_confirm_token_for_live_execution


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _mint_token(*, secret: str, scope: str, iat: int, exp: int, jti: str | None = None) -> str:
    payload = {
        "jti": jti or secrets.token_urlsafe(24),
        "scope": scope,
        "iat": int(iat),
        "exp": int(exp),
    }
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"v1.{payload_b64}".encode("utf-8")
    sig = _b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"v1.{payload_b64}.{sig}"


def _guarded_broker_call(*, token: str | None, broker_callable, expected_scope: str, now_s: int | None = None) -> None:
    require_confirm_token_for_live_execution(
        provided_token=token,
        expected_scope=expected_scope,
        now_epoch_s=now_s,
    )
    broker_callable()


@pytest.fixture()
def _isolated_replay_store(tmp_path, monkeypatch):
    # Ensure single-use/replay checks don't leak across tests.
    monkeypatch.setenv("EXECUTION_CONFIRM_REPLAY_DIR", str(tmp_path / "replay"))
    return tmp_path


def test_token_replay_across_executions_is_refused_and_broker_not_called(_isolated_replay_store, monkeypatch):
    secret = "test-secret-replay"
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", secret)

    now = int(time.time())
    token = _mint_token(secret=secret, scope="execution.execute_intent", iat=now, exp=now + 60, jti="replay_jti_0000000001")

    called = {"n": 0}

    def broker_submit():
        called["n"] += 1

    # First use succeeds and reaches broker callable.
    _guarded_broker_call(token=token, broker_callable=broker_submit, expected_scope="execution.execute_intent", now_s=now)
    assert called["n"] == 1

    # Second use must fail (replay) and must NOT reach broker callable.
    with pytest.raises(ExecutionConfirmTokenError) as e:
        _guarded_broker_call(token=token, broker_callable=broker_submit, expected_scope="execution.execute_intent", now_s=now)
    assert "replay" in str(e.value).lower()
    assert called["n"] == 1


def test_token_reused_across_processes_is_refused(_isolated_replay_store, monkeypatch):
    secret = "test-secret-process"
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", secret)

    now = int(time.time())
    token = _mint_token(secret=secret, scope="execution.execute_intent", iat=now, exp=now + 60, jti="process_jti_0000000002")

    q: Queue = Queue()

    def _use_once(result_q: Queue):
        try:
            require_confirm_token_for_live_execution(provided_token=token, expected_scope="execution.execute_intent", now_epoch_s=now)
            result_q.put(("ok", None))
        except Exception as ex:  # pragma: no cover - exercised via child processes
            result_q.put(("err", str(ex)))

    p1 = Process(target=_use_once, args=(q,))
    p2 = Process(target=_use_once, args=(q,))
    p1.start()
    p1.join(timeout=10)
    p2.start()
    p2.join(timeout=10)

    out1 = q.get(timeout=3)
    out2 = q.get(timeout=3)
    # Order is not guaranteed; assert one ok and one replay error.
    statuses = {out1[0], out2[0]}
    assert statuses == {"ok", "err"}
    err_msg = out1[1] if out1[0] == "err" else out2[1]
    assert err_msg is not None
    assert "replay" in err_msg.lower()


def test_token_with_altered_scope_is_refused_and_broker_not_called(_isolated_replay_store, monkeypatch):
    secret = "test-secret-scope"
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", secret)

    now = int(time.time())
    token = _mint_token(secret=secret, scope="execution.cancel_order", iat=now, exp=now + 60, jti="scope_jti_0000000003")

    called = {"n": 0}

    def broker_submit():
        called["n"] += 1

    with pytest.raises(ExecutionConfirmTokenError) as e:
        _guarded_broker_call(token=token, broker_callable=broker_submit, expected_scope="execution.execute_intent", now_s=now)
    msg = str(e.value).lower()
    assert "scope mismatch" in msg
    assert called["n"] == 0


def test_token_after_timeout_is_refused_and_broker_not_called(_isolated_replay_store, monkeypatch):
    secret = "test-secret-expired"
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", secret)

    now = int(time.time())
    token = _mint_token(secret=secret, scope="execution.execute_intent", iat=now - 120, exp=now - 1, jti="expired_jti_0000000004")

    called = {"n": 0}

    def broker_submit():
        called["n"] += 1

    with pytest.raises(ExecutionConfirmTokenError) as e:
        _guarded_broker_call(token=token, broker_callable=broker_submit, expected_scope="execution.execute_intent", now_s=now)
    assert "expired" in str(e.value).lower()
    assert called["n"] == 0

