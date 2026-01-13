import pytest

from backend.common.env import assert_paper_alpaca_base_url as backend_assert_paper_alpaca_base_url
from backend.common.env import get_alpaca_api_base_url
from backend.streams.alpaca_env import _looks_like_live_trading_host, default_trading_paper_flag
from functions.utils.apca_env import (
    assert_paper_alpaca_base_url as functions_assert_paper_alpaca_base_url,
)


@pytest.mark.parametrize(
    "validator",
    [
        backend_assert_paper_alpaca_base_url,
        functions_assert_paper_alpaca_base_url,
    ],
)
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://paper-api.alpaca.markets", "https://paper-api.alpaca.markets"),
        ("https://paper-api.alpaca.markets/", "https://paper-api.alpaca.markets"),
        ("https://paper-api.alpaca.markets/v2", "https://paper-api.alpaca.markets/v2"),
        ("https://paper-api.alpaca.markets/v2/", "https://paper-api.alpaca.markets/v2"),
    ],
)
def test_assert_paper_alpaca_base_url_allows_paper_host(validator, raw: str, expected: str):
    assert validator(raw) == expected


@pytest.mark.parametrize(
    "validator",
    [
        backend_assert_paper_alpaca_base_url,
        functions_assert_paper_alpaca_base_url,
    ],
)
@pytest.mark.parametrize(
    "raw",
    [
        "https://api.alpaca.markets",
        "https://api.alpaca.markets/v2",
        # Confusing-but-dangerous case: live host with a paper-ish path.
        # Still must be rejected (host is NOT paper-api.alpaca.markets).
        "https://api.alpaca.markets/paper-api.alpaca.markets/v2",
    ],
)
def test_assert_paper_alpaca_base_url_rejects_live_host(validator, raw: str):
    # Note: the implementation first does a substring "live host" precheck, then
    # enforces exact hostname. Some strings may fail at the hostname check first,
    # so accept either refusal reason.
    with pytest.raises(
        RuntimeError,
        match=r"REFUSED: (live Alpaca trading host is forbidden|Alpaca base URL must be paper host)",
    ):
        validator(raw)


@pytest.mark.parametrize(
    "validator",
    [
        backend_assert_paper_alpaca_base_url,
        functions_assert_paper_alpaca_base_url,
    ],
)
@pytest.mark.parametrize(
    "raw,match",
    [
        ("https://example.com", "REFUSED: Alpaca base URL must be paper host"),
        # Subdomain tricks should be rejected (hostname must be exact).
        ("https://paper-api.alpaca.markets.evil.com", "REFUSED: Alpaca base URL must be paper host"),
        # Userinfo tricks: exact hostname enforcement should still reject.
        ("https://paper-api.alpaca.markets@evil.com", "REFUSED: Alpaca base URL must be paper host"),
    ],
)
def test_assert_paper_alpaca_base_url_rejects_any_other_host(validator, raw: str, match: str):
    with pytest.raises(RuntimeError, match=match):
        validator(raw)


def test_get_alpaca_api_base_url_normalizes_and_enforces_paper(monkeypatch):
    # Ensures get_alpaca_api_base_url() strips trailing slash and applies the paper-host validator.
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/")
    assert get_alpaca_api_base_url(required=True) == "https://paper-api.alpaca.markets"


def test_get_alpaca_api_base_url_rejects_live_host_even_if_set(monkeypatch):
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    with pytest.raises(RuntimeError, match="REFUSED: live Alpaca trading host is forbidden"):
        _ = get_alpaca_api_base_url(required=True)


def test_live_trading_host_detection_and_default_paper_flag():
    # "Live URL validation" (best-effort): live host should be detected as live.
    assert _looks_like_live_trading_host("https://api.alpaca.markets") is True
    assert _looks_like_live_trading_host("https://api.alpaca.markets/v2") is True

    # Paper host must not be detected as live.
    assert _looks_like_live_trading_host("https://paper-api.alpaca.markets") is False
    assert _looks_like_live_trading_host("https://paper-api.alpaca.markets/v2") is False

    # Other Alpaca hosts (data endpoints) are not live trading.
    assert _looks_like_live_trading_host("https://data.alpaca.markets") is False

    # default_trading_paper_flag() flips paper=False only for live trading host.
    assert default_trading_paper_flag("https://api.alpaca.markets") is False
    assert default_trading_paper_flag("https://paper-api.alpaca.markets") is True
    assert default_trading_paper_flag("https://data.alpaca.markets") is True

