import pytest


from backend.common.ws_reconnect_policy import classify_ws_failure, ensure_retry_allowed


class _ExcWithStatus(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def test_classify_ws_failure_auth_by_status_code() -> None:
    info = classify_ws_failure(_ExcWithStatus("handshake failed", 401))
    assert info.category == "auth_failure"
    assert info.http_status == 401


def test_classify_ws_failure_rate_limited_by_status_code() -> None:
    info = classify_ws_failure(_ExcWithStatus("handshake failed", 429))
    assert info.category == "rate_limited"
    assert info.http_status == 429


def test_classify_ws_failure_auth_by_message_match() -> None:
    info = classify_ws_failure(Exception("Auth failed: invalid API key"))
    assert info.category == "auth_failure"


def test_retry_guard_allows_exact_max_attempts() -> None:
    # backoff attempt counter is 1-based; allow exactly max_attempts retries
    for attempt in range(1, 6):
        ensure_retry_allowed(attempt=attempt, max_attempts=5)


def test_retry_guard_blocks_attempts_above_cap() -> None:
    with pytest.raises(RuntimeError):
        ensure_retry_allowed(attempt=6, max_attempts=5)

