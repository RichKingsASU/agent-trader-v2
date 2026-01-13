import pytest

from backend.common.execution_confirm import (
    ExecutionConfirmTokenError,
    require_confirm_token_for_live_execution,
)


def test_valid_token_passes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "s3cr3t-token")
    require_confirm_token_for_live_execution(provided_token="s3cr3t-token")


def test_missing_expected_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXECUTION_CONFIRM_TOKEN", raising=False)
    with pytest.raises(
        ExecutionConfirmTokenError,
        match=r"Refusing live execution: EXECUTION_CONFIRM_TOKEN is missing/empty",
    ):
        require_confirm_token_for_live_execution(provided_token="anything")


@pytest.mark.parametrize("provided_token", [None, "", "   "])
def test_missing_provided_token_fails(monkeypatch: pytest.MonkeyPatch, provided_token: str | None) -> None:
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "s3cr3t-token")
    with pytest.raises(
        ExecutionConfirmTokenError,
        match=r"Refusing live execution: missing confirmation token .*X-Exec-Confirm-Token",
    ):
        require_confirm_token_for_live_execution(provided_token=provided_token)


def test_mismatched_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "s3cr3t-token")
    with pytest.raises(
        ExecutionConfirmTokenError,
        match=r"Refusing live execution: confirmation token mismatch\.",
    ):
        require_confirm_token_for_live_execution(provided_token="wrong-token")


# --- vNEXT security hardening expectations (spec tests) ---
# The current implementation only compares strings. These tests codify the
# expected security posture for "confirmation tokens" once the feature is
# fully enforced (single-use + expiry + strict format checks).


@pytest.mark.xfail(strict=True, reason="single-use confirmation tokens not enforced yet")
def test_token_reuse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "one-time-token")

    # First use should succeed.
    require_confirm_token_for_live_execution(provided_token="one-time-token")

    # Second use of the same token should fail (anti-replay).
    with pytest.raises(ExecutionConfirmTokenError, match=r"reuse|replay|already used"):
        require_confirm_token_for_live_execution(provided_token="one-time-token")


@pytest.mark.xfail(strict=True, reason="expiry validation not enforced yet")
def test_expired_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Intentionally choose a token that *looks* time-bound; once expiry parsing
    # is implemented, this should be rejected as expired.
    expired = "v1:exp=1970-01-01T00:00:00Z:token=s3cr3t"
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", expired)

    with pytest.raises(ExecutionConfirmTokenError, match=r"expired|expiry"):
        require_confirm_token_for_live_execution(provided_token=expired)


@pytest.mark.xfail(strict=True, reason="malformed token / header-injection hardening not enforced yet")
def test_malformed_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_CONFIRM_TOKEN", "s3cr3t-token")

    # Malformed / potentially dangerous input: contains newline.
    with pytest.raises(ExecutionConfirmTokenError, match=r"malformed|invalid|header"):
        require_confirm_token_for_live_execution(provided_token="s3cr3t-token\nX-Evil: 1")

