"""
Tests for WhaleFlowService.

Tests the ingestion, conviction scoring, and lookback functionality.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

from backend.services.whale_flow import WhaleFlowService, get_recent_conviction


@pytest.fixture
def mock_db():
    """Create a mock Firestore client."""
    return Mock()


@pytest.fixture
def service(mock_db):
    """Create a WhaleFlowService instance with mock DB."""
    return WhaleFlowService(db=mock_db)


class TestMapFlowToSchema:
    """Test mapping of raw flow data to Firestore schema."""
    
    def test_basic_mapping(self, service):
        """Test basic field mapping."""
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "spy",
            "option_symbol": "SPY251219C00400000",
            "side": "buy",
            "size": 100,
            "premium": 10000.50,
            "strike_price": 400.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 4.00,
            "bid_price": 3.90,
            "ask_price": 4.10,
            "spot_price": 395.00,
            "implied_volatility": 0.25,
            "open_interest": 500,
            "volume": 200,
        }
        
        result = service.map_flow_to_schema("user123", flow_data)
        
        assert result["underlying_symbol"] == "SPY"  # Uppercase
        assert result["option_symbol"] == "SPY251219C00400000"
        assert result["side"] == "buy"
        assert result["size"] == 100
        assert result["premium"] == "10000.50"
        assert result["strike_price"] == "400.00"
        assert result["expiration_date"] == "2025-12-19"
        assert result["option_type"] == "CALL"
        assert result["spot_price"] == "395.00"
        assert result["is_otm"] is True  # Call with strike > spot
        assert "conviction_score" in result
    
    def test_sweep_detection(self, service):
        """Test SWEEP detection when trade at ask."""
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "AAPL",
            "option_symbol": "AAPL251219C00230000",
            "side": "buy",
            "size": 50,
            "premium": 5000,
            "strike_price": 230.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 4.10,  # At ask
            "bid_price": 3.90,
            "ask_price": 4.10,
            "spot_price": 225.00,
        }
        
        result = service.map_flow_to_schema("user123", flow_data)
        
        assert result["flow_type"] == "SWEEP"
        assert result["sentiment"] == "BULLISH"  # Call bought at ask
    
    def test_block_detection(self, service):
        """Test BLOCK detection for large size."""
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "TSLA",
            "option_symbol": "TSLA251219P00400000",
            "side": "buy",
            "size": 150,  # Large size
            "premium": 15000,
            "strike_price": 400.00,
            "expiration_date": "2025-12-19",
            "option_type": "put",
            "trade_price": 3.50,
            "bid_price": 3.40,
            "ask_price": 3.60,
            "spot_price": 410.00,
        }
        
        result = service.map_flow_to_schema("user123", flow_data)
        
        assert result["flow_type"] == "BLOCK"
    
    def test_vol_oi_ratio_calculation(self, service):
        """Test volume/OI ratio calculation."""
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "NVDA",
            "option_symbol": "NVDA251219C00140000",
            "side": "buy",
            "size": 100,
            "premium": 5000,
            "strike_price": 140.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 2.50,
            "bid_price": 2.40,
            "ask_price": 2.60,
            "spot_price": 138.00,
            "volume": 600,
            "open_interest": 400,
        }
        
        result = service.map_flow_to_schema("user123", flow_data)
        
        # vol_oi_ratio = 600 / 400 = 1.5
        assert result["vol_oi_ratio"] == "1.50"
    
    def test_missing_optional_fields(self, service):
        """Test handling of missing optional fields."""
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "SPY",
            "option_symbol": "SPY251219C00400000",
            "side": "buy",
            "size": 100,
            "premium": 10000,
        }
        
        result = service.map_flow_to_schema("user123", flow_data)
        
        assert result["underlying_symbol"] == "SPY"
        assert result["spot_price"] is None
        assert result["implied_volatility"] is None
        assert result["is_otm"] is False  # Can't determine without prices


class TestConvictionScore:
    """Test conviction score calculation."""
    
    def test_sweep_base_score(self, service):
        """Test SWEEP gets base score of 0.8."""
        flow_data = {
            "flow_type": "SWEEP",
            "is_otm": False,
            "vol_oi_ratio": None,
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("0.80")
    
    def test_block_base_score(self, service):
        """Test BLOCK gets base score of 0.5."""
        flow_data = {
            "flow_type": "BLOCK",
            "is_otm": False,
            "vol_oi_ratio": None,
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("0.50")
    
    def test_otm_boost(self, service):
        """Test +0.1 boost for OTM."""
        flow_data = {
            "flow_type": "BLOCK",
            "is_otm": True,
            "vol_oi_ratio": None,
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("0.60")  # 0.5 + 0.1
    
    def test_vol_oi_boost(self, service):
        """Test +0.1 boost for vol/OI > 1.2."""
        flow_data = {
            "flow_type": "BLOCK",
            "is_otm": False,
            "vol_oi_ratio": "1.5",
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("0.60")  # 0.5 + 0.1
    
    def test_maximum_score(self, service):
        """Test maximum score with all boosts."""
        flow_data = {
            "flow_type": "SWEEP",
            "is_otm": True,
            "vol_oi_ratio": "2.0",
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("1.00")  # 0.8 + 0.1 + 0.1
    
    def test_unknown_flow_type(self, service):
        """Test unknown flow type gets lower base score."""
        flow_data = {
            "flow_type": "UNKNOWN",
            "is_otm": False,
            "vol_oi_ratio": None,
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score == Decimal("0.30")
    
    def test_score_clamping(self, service):
        """Test score is clamped to [0, 1]."""
        flow_data = {
            "flow_type": "SWEEP",
            "is_otm": True,
            "vol_oi_ratio": "3.0",
        }
        
        score = service.calculate_conviction_score(flow_data)
        
        assert score <= Decimal("1.00")
        assert score >= Decimal("0.00")


class TestIngestFlow:
    """Test flow ingestion."""
    
    def test_ingest_single_flow(self, service, mock_db):
        """Test ingesting a single flow."""
        # Setup mock
        mock_collection = Mock()
        mock_doc_ref = Mock()
        mock_doc_ref.set = Mock()
        mock_collection.document.return_value = mock_doc_ref
        
        mock_user_doc = Mock()
        mock_user_doc.collection.return_value = mock_collection
        
        mock_users_collection = Mock()
        mock_users_collection.document.return_value = mock_user_doc
        
        mock_db.collection.return_value = mock_users_collection
        
        flow_data = {
            "timestamp": "2025-12-30T12:00:00Z",
            "underlying_symbol": "SPY",
            "option_symbol": "SPY251219C00400000",
            "side": "buy",
            "size": 100,
            "premium": 10000,
            "strike_price": 400.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 4.00,
            "bid_price": 3.90,
            "ask_price": 4.10,
        }
        
        doc_id = service.ingest_flow("user123", flow_data, doc_id="flow_001")
        
        assert doc_id == "flow_001"
        mock_db.collection.assert_called_with("users")
        mock_doc_ref.set.assert_called_once()
    
    def test_ingest_batch(self, service, mock_db):
        """Test batch ingestion."""
        # Setup mock
        mock_collection = Mock()
        mock_batch = Mock()
        mock_batch.commit = Mock()
        mock_db.batch.return_value = mock_batch
        
        mock_doc_ref = Mock()
        mock_doc_ref.id = "doc_001"
        mock_collection.document.return_value = mock_doc_ref
        
        mock_user_doc = Mock()
        mock_user_doc.collection.return_value = mock_collection
        
        mock_users_collection = Mock()
        mock_users_collection.document.return_value = mock_user_doc
        
        mock_db.collection.return_value = mock_users_collection
        
        flows = [
            {
                "timestamp": "2025-12-30T12:00:00Z",
                "underlying_symbol": "SPY",
                "option_symbol": "SPY251219C00400000",
                "side": "buy",
                "size": 100,
                "premium": 10000,
            },
            {
                "timestamp": "2025-12-30T12:05:00Z",
                "underlying_symbol": "QQQ",
                "option_symbol": "QQQ251219P00500000",
                "side": "sell",
                "size": 50,
                "premium": 5000,
            },
        ]
        
        doc_ids = service.ingest_batch("user123", flows)
        
        assert len(doc_ids) == 2
        mock_batch.commit.assert_called_once()


class TestGetRecentConviction:
    """Test get_recent_conviction functionality."""
    
    def test_no_recent_activity(self, service, mock_db):
        """Test when there's no recent activity."""
        # Setup mock to return empty results
        mock_query = Mock()
        mock_query.stream.return_value = []
        
        mock_collection = Mock()
        mock_collection.where.return_value.where.return_value.order_by.return_value.limit.return_value = mock_query
        
        mock_user_doc = Mock()
        mock_user_doc.collection.return_value = mock_collection
        
        mock_users_collection = Mock()
        mock_users_collection.document.return_value = mock_user_doc
        
        mock_db.collection.return_value = mock_users_collection
        
        result = service.get_recent_conviction("user123", "AAPL", lookback_minutes=30)
        
        assert result["has_activity"] is False
        assert result["total_flows"] == 0
        assert result["avg_conviction"] == Decimal("0")
        assert result["dominant_sentiment"] == "NEUTRAL"
    
    def test_with_recent_activity(self, service, mock_db):
        """Test with recent bullish activity."""
        # Create mock flow documents
        mock_doc1 = Mock()
        mock_doc1.to_dict.return_value = {
            "underlying_symbol": "AAPL",
            "conviction_score": "0.80",
            "sentiment": "BULLISH",
            "premium": "5000.00",
        }
        
        mock_doc2 = Mock()
        mock_doc2.to_dict.return_value = {
            "underlying_symbol": "AAPL",
            "conviction_score": "0.90",
            "sentiment": "BULLISH",
            "premium": "7000.00",
        }
        
        # Setup mock query
        mock_query = Mock()
        mock_query.stream.return_value = [mock_doc1, mock_doc2]
        
        mock_collection = Mock()
        mock_collection.where.return_value.where.return_value.order_by.return_value.limit.return_value = mock_query
        
        mock_user_doc = Mock()
        mock_user_doc.collection.return_value = mock_collection
        
        mock_users_collection = Mock()
        mock_users_collection.document.return_value = mock_user_doc
        
        mock_db.collection.return_value = mock_users_collection
        
        result = service.get_recent_conviction("user123", "AAPL", lookback_minutes=30)
        
        assert result["has_activity"] is True
        assert result["total_flows"] == 2
        assert result["avg_conviction"] == Decimal("0.85")  # (0.8 + 0.9) / 2
        assert result["max_conviction"] == Decimal("0.90")
        assert result["bullish_flows"] == 2
        assert result["bearish_flows"] == 0
        assert result["total_premium"] == Decimal("12000.00")
        assert result["dominant_sentiment"] == "BULLISH"
    
    def test_mixed_sentiment(self, service, mock_db):
        """Test with mixed sentiment activity."""
        # Create mock flow documents
        mock_docs = [
            Mock(to_dict=lambda: {
                "conviction_score": "0.70",
                "sentiment": "BULLISH",
                "premium": "3000.00",
            }),
            Mock(to_dict=lambda: {
                "conviction_score": "0.65",
                "sentiment": "BEARISH",
                "premium": "2500.00",
            }),
            Mock(to_dict=lambda: {
                "conviction_score": "0.75",
                "sentiment": "BULLISH",
                "premium": "4000.00",
            }),
        ]
        
        mock_query = Mock()
        mock_query.stream.return_value = mock_docs
        
        mock_collection = Mock()
        mock_collection.where.return_value.where.return_value.order_by.return_value.limit.return_value = mock_query
        
        mock_user_doc = Mock()
        mock_user_doc.collection.return_value = mock_collection
        
        mock_users_collection = Mock()
        mock_users_collection.document.return_value = mock_user_doc
        
        mock_db.collection.return_value = mock_users_collection
        
        result = service.get_recent_conviction("user123", "TSLA", lookback_minutes=30)
        
        assert result["total_flows"] == 3
        assert result["bullish_flows"] == 2
        assert result["bearish_flows"] == 1
        assert result["dominant_sentiment"] == "MIXED"  # Not enough to be purely bullish


class TestHelperMethods:
    """Test helper methods."""
    
    def test_parse_timestamp_iso(self, service):
        """Test parsing ISO timestamp."""
        timestamp = "2025-12-30T12:00:00Z"
        result = service._parse_timestamp(timestamp)
        
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
    
    def test_parse_timestamp_datetime(self, service):
        """Test parsing datetime object."""
        timestamp = datetime(2025, 12, 30, 12, 0, 0, tzinfo=timezone.utc)
        result = service._parse_timestamp(timestamp)
        
        assert result == timestamp
    
    def test_to_decimal(self, service):
        """Test conversion to Decimal."""
        assert service._to_decimal(100.50) == Decimal("100.50")
        assert service._to_decimal("100.50") == Decimal("100.50")
        assert service._to_decimal(None) is None
    
    def test_is_otm_call(self, service):
        """Test OTM detection for calls."""
        # Call with strike > spot is OTM
        assert service._is_otm("CALL", Decimal("400"), Decimal("395")) is True
        assert service._is_otm("CALL", Decimal("395"), Decimal("400")) is False
    
    def test_is_otm_put(self, service):
        """Test OTM detection for puts."""
        # Put with strike < spot is OTM
        assert service._is_otm("PUT", Decimal("395"), Decimal("400")) is True
        assert service._is_otm("PUT", Decimal("400"), Decimal("395")) is False
    
    def test_determine_sentiment_bullish(self, service):
        """Test bullish sentiment detection."""
        # Call bought at ask
        sentiment = service._determine_sentiment(
            "CALL", "buy", Decimal("4.10"), Decimal("3.90"), Decimal("4.10")
        )
        assert sentiment == "BULLISH"
    
    def test_determine_sentiment_bearish(self, service):
        """Test bearish sentiment detection."""
        # Put bought at ask
        sentiment = service._determine_sentiment(
            "PUT", "buy", Decimal("3.60"), Decimal("3.40"), Decimal("3.60")
        )
        assert sentiment == "BEARISH"


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    @patch('backend.services.whale_flow.WhaleFlowService')
    def test_get_recent_conviction_function(self, mock_service_class):
        """Test get_recent_conviction convenience function."""
        mock_service = Mock()
        mock_service.get_recent_conviction.return_value = {
            "ticker": "AAPL",
            "has_activity": True,
            "avg_conviction": Decimal("0.85"),
        }
        mock_service_class.return_value = mock_service
        
        result = get_recent_conviction("user123", "AAPL", lookback_minutes=30)
        
        assert result["ticker"] == "AAPL"
        assert result["has_activity"] is True
        mock_service.get_recent_conviction.assert_called_once_with("user123", "AAPL", 30)
