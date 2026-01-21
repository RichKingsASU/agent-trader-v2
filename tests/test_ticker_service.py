"""
Tests for the ticker service real-time market data feed.
"""

import os
import pytest
from unittest.mock import Mock, patch, AsyncMock

try:  # pragma: no cover
    import alpaca_trade_api  # noqa: F401
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"ticker_service depends on optional alpaca_trade_api dependency: {type(e).__name__}: {e}",
        strict=False,
    )


def test_ticker_service_import():
    """Test that ticker_service module can be imported."""
    from functions import ticker_service
    assert ticker_service is not None


def test_get_alpaca_credentials_success(monkeypatch):
    """Test credential retrieval with valid environment variables."""
    from functions.ticker_service import _get_alpaca_credentials
    
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key_id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    
    creds = _get_alpaca_credentials()
    
    assert creds["key_id"] == "test_key_id"
    assert creds["secret_key"] == "test_secret_key"
    assert creds["base_url"] == "https://paper-api.alpaca.markets"


def test_get_alpaca_credentials_missing_key(monkeypatch):
    """Test that missing credentials raise a RuntimeError."""
    from functions.ticker_service import _get_alpaca_credentials
    
    # Clear any existing credentials
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)
    
    with pytest.raises(RuntimeError, match="Missing required env var"):
        _get_alpaca_credentials()


def test_get_alpaca_credentials_with_apca_prefix(monkeypatch):
    """Test credential retrieval with APCA_ prefixed environment variables."""
    from functions.ticker_service import _get_alpaca_credentials
    
    monkeypatch.setenv("APCA_API_KEY_ID", "apca_key_id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "apca_secret_key")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
    
    creds = _get_alpaca_credentials()
    
    assert creds["key_id"] == "apca_key_id"
    assert creds["secret_key"] == "apca_secret_key"
    assert creds["base_url"] == "https://paper-api.alpaca.markets"


def test_get_target_symbols_default():
    """Test default symbols are returned when not configured."""
    from functions.ticker_service import _get_target_symbols
    
    symbols = _get_target_symbols()
    
    assert "AAPL" in symbols
    assert "NVDA" in symbols
    assert "TSLA" in symbols


def test_get_target_symbols_custom(monkeypatch):
    """Test custom symbols can be configured via environment."""
    from functions.ticker_service import _get_target_symbols
    
    monkeypatch.setenv("TICKER_SYMBOLS", "SPY,QQQ,IWM")
    
    symbols = _get_target_symbols()
    
    assert symbols == ["SPY", "QQQ", "IWM"]


def test_get_target_symbols_lowercase_converted(monkeypatch):
    """Test that lowercase symbols are converted to uppercase."""
    from functions.ticker_service import _get_target_symbols
    
    monkeypatch.setenv("TICKER_SYMBOLS", "aapl,nvda")
    
    symbols = _get_target_symbols()
    
    assert symbols == ["AAPL", "NVDA"]


def test_get_target_symbols_whitespace_handled(monkeypatch):
    """Test that whitespace in symbol list is properly handled."""
    from functions.ticker_service import _get_target_symbols
    
    monkeypatch.setenv("TICKER_SYMBOLS", " AAPL , NVDA , TSLA ")
    
    symbols = _get_target_symbols()
    
    assert symbols == ["AAPL", "NVDA", "TSLA"]


@patch('functions.ticker_service._get_firestore')
@patch('functions.ticker_service._get_alpaca_credentials')
def test_ticker_service_initialization(mock_creds, mock_firestore, monkeypatch):
    """Test TickerService can be initialized."""
    from functions.ticker_service import TickerService
    
    mock_creds.return_value = {
        "key_id": "test_key",
        "secret_key": "test_secret",
        "base_url": "https://paper-api.alpaca.markets"
    }
    mock_firestore.return_value = Mock()
    monkeypatch.setenv("TICKER_SYMBOLS", "AAPL")
    
    service = TickerService()
    
    assert service.symbols == ["AAPL"]
    assert service.credentials["key_id"] == "test_key"
    assert service.max_retries == 5
    assert service.retry_delay == 5


@patch('functions.ticker_service._get_firestore')
@patch('functions.ticker_service._get_alpaca_credentials')
@pytest.mark.asyncio
async def test_handle_bar(mock_creds, mock_firestore, monkeypatch):
    """Test bar data handling and Firestore upsert."""
    from functions.ticker_service import TickerService
    from datetime import datetime, timezone
    
    mock_creds.return_value = {
        "key_id": "test_key",
        "secret_key": "test_secret",
        "base_url": "https://paper-api.alpaca.markets"
    }
    
    mock_db = Mock()
    mock_collection = Mock()
    mock_doc = Mock()
    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc
    mock_firestore.return_value = mock_db
    
    monkeypatch.setenv("TICKER_SYMBOLS", "AAPL")
    
    service = TickerService()
    
    # Create a mock bar object
    mock_bar = Mock()
    mock_bar.symbol = "AAPL"
    mock_bar.timestamp = datetime(2025, 12, 30, 14, 30, 0, tzinfo=timezone.utc)
    mock_bar.open = 195.42
    mock_bar.high = 195.88
    mock_bar.low = 195.35
    mock_bar.close = 195.67
    mock_bar.volume = 125000
    
    await service._handle_bar(mock_bar)
    
    # Verify Firestore was called
    mock_db.collection.assert_called_once_with("marketData")
    mock_collection.document.assert_called_once_with("AAPL")
    mock_doc.set.assert_called_once()
    
    # Verify data structure
    call_args = mock_doc.set.call_args
    data = call_args[0][0]
    assert data["symbol"] == "AAPL"
    assert data["open"] == 195.42
    assert data["high"] == 195.88
    assert data["low"] == 195.35
    assert data["close"] == 195.67
    assert data["volume"] == 125000


@patch('functions.ticker_service._get_firestore')
@patch('functions.ticker_service._get_alpaca_credentials')
@pytest.mark.asyncio
async def test_handle_bar_with_dict_format(mock_creds, mock_firestore, monkeypatch):
    """Test bar data handling with dictionary format (alternative bar format)."""
    from functions.ticker_service import TickerService
    
    mock_creds.return_value = {
        "key_id": "test_key",
        "secret_key": "test_secret",
        "base_url": "https://paper-api.alpaca.markets"
    }
    
    mock_db = Mock()
    mock_collection = Mock()
    mock_doc = Mock()
    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc
    mock_firestore.return_value = mock_db
    
    monkeypatch.setenv("TICKER_SYMBOLS", "NVDA")
    
    service = TickerService()
    
    # Create a mock bar as dictionary
    mock_bar = {
        'S': 'NVDA',
        't': '2025-12-30T14:30:00Z',
        'o': 500.25,
        'h': 502.50,
        'l': 499.75,
        'c': 501.80,
        'v': 250000
    }
    
    await service._handle_bar(mock_bar)
    
    # Verify Firestore was called correctly
    mock_db.collection.assert_called_once_with("marketData")
    mock_collection.document.assert_called_once_with("NVDA")
    mock_doc.set.assert_called_once()


@patch('functions.ticker_service._get_firestore')
@patch('functions.ticker_service._get_alpaca_credentials')
@pytest.mark.asyncio
async def test_stop_service(mock_creds, mock_firestore, monkeypatch):
    """Test service can be stopped gracefully."""
    from functions.ticker_service import TickerService
    
    mock_creds.return_value = {
        "key_id": "test_key",
        "secret_key": "test_secret",
        "base_url": "https://paper-api.alpaca.markets"
    }
    mock_firestore.return_value = Mock()
    monkeypatch.setenv("TICKER_SYMBOLS", "AAPL")
    
    service = TickerService()
    service.running = True
    service.conn = AsyncMock()
    
    await service.stop()
    
    assert service.running is False
    service.conn.close.assert_called_once()
