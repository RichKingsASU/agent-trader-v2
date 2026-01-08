import pytest


def test_load_alpaca_env_missing_fails_fast(monkeypatch):
    from backend.config.alpaca_env import load_alpaca_env

    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match=r"Missing required Alpaca env vars:"):
        load_alpaca_env()


def test_load_alpaca_env_success(monkeypatch):
    from backend.config.alpaca_env import load_alpaca_env

    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    env = load_alpaca_env()
    assert env.key_id == "k"
    assert env.secret_key == "s"
    assert env.base_url == "https://paper-api.alpaca.markets"

