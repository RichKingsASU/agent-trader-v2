import pytest


@pytest.fixture(autouse=True)
def _disable_market_open_guard_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Prevent time-of-day flakes in CI.

    Guard-specific tests explicitly override this.
    """

    monkeypatch.setenv("MARKET_OPEN_BLOCK_MINUTES", "0")

