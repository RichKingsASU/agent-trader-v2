import pytest


def _call_guard():
    # Import inside helper so monkeypatched env applies cleanly per test.
    from backend.common.agent_mode_guard import enforce_agent_mode_guard

    return enforce_agent_mode_guard()


def test_missing_trading_mode_hard_fails(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    with pytest.raises(SystemExit) as e:
        _call_guard()

    assert e.value.code == 13
    err = capsys.readouterr().err
    assert "TRADING_MODE is missing/empty" in err


def test_invalid_agent_mode_hard_fails(monkeypatch, capsys):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("AGENT_MODE", "NOT_A_MODE")

    with pytest.raises(SystemExit) as e:
        _call_guard()

    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "Invalid AGENT_MODE" in err
    assert "Allowed:" in err


def test_paper_mode_with_live_alpaca_url_hard_fails(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")

    with pytest.raises(SystemExit) as e:
        _call_guard()

    assert e.value.code == 13
    err = capsys.readouterr().err
    assert "TRADING_MODE=paper" in err
    assert "paper-api.alpaca.markets" in err
    assert "APCA_API_BASE_URL" in err


def test_live_mode_with_paper_alpaca_url_hard_fails(monkeypatch, capsys):
    monkeypatch.setenv("AGENT_MODE", "OFF")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    with pytest.raises(SystemExit) as e:
        _call_guard()

    assert e.value.code == 13
    err = capsys.readouterr().err
    assert "TRADING_MODE=live" in err
    assert "api.alpaca.markets" in err
    assert "APCA_API_BASE_URL" in err

