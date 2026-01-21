"""
Tests for Maestro Orchestration Layer

Tests cover:
- Sharpe-based allocation adjustments
- Systemic risk detection and override
- JIT Identity generation and uniqueness
- Performance metrics calculation
- Integration with StrategyLoader
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, MagicMock, patch

# Import components to test
try:
    from functions.strategies.maestro_controller import (
        MaestroController,
        AgentMode,
        AgentIdentity,
        StrategyPerformanceMetrics,
        AllocationDecision,
        MaestroDecision,
    )
    from functions.strategies.loader import StrategyLoader
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"Maestro orchestration depends on optional cloud deps (e.g. Firestore): {type(e).__name__}: {e}",
        strict=False,
    )


class MockFirestoreClient:
    """Mock Firestore client for testing."""
    
    def __init__(self):
        self.collections = {}
        self.documents = {}
    
    def collection(self, path: str):
        if path not in self.collections:
            self.collections[path] = MockCollection(path)
        return self.collections[path]
    
    def document(self, path: str):
        if path not in self.documents:
            self.documents[path] = MockDocument(path)
        return self.documents[path]


class MockCollection:
    """Mock Firestore collection."""
    
    def __init__(self, path: str):
        self.path = path
        self.docs = []
        self._where_filters = []
        self._order_by_field = None
        self._limit_value = None
    
    def document(self, doc_id: str = None):
        return MockDocument(f"{self.path}/{doc_id or 'auto-id'}")
    
    def where(self, field, op, value):
        self._where_filters.append((field, op, value))
        return self
    
    def order_by(self, field, direction=None):
        self._order_by_field = field
        return self
    
    def limit(self, count):
        self._limit_value = count
        return self
    
    def stream(self):
        return iter(self.docs)
    
    def add_mock_doc(self, data: Dict):
        doc = MockDocumentSnapshot(data)
        self.docs.append(doc)


class MockDocument:
    """Mock Firestore document."""
    
    def __init__(self, path: str):
        self.path = path
        self._data = None
    
    def set(self, data: Dict, merge: bool = False):
        self._data = data
    
    def get(self):
        return MockDocumentSnapshot(self._data or {})
    
    def collection(self, name: str):
        return MockCollection(f"{self.path}/{name}")


class MockDocumentSnapshot:
    """Mock Firestore document snapshot."""
    
    def __init__(self, data: Dict):
        self._data = data
        self.exists = data is not None
    
    def to_dict(self):
        return self._data or {}


@pytest.fixture
def mock_db():
    """Provide mock Firestore client."""
    return MockFirestoreClient()


@pytest.fixture
def maestro(mock_db):
    """Provide MaestroController instance."""
    return MaestroController(
        db=mock_db,
        tenant_id="test-tenant",
        uid="test-user"
    )


@pytest.fixture
def mock_strategies():
    """Provide mock strategy instances."""
    return {
        "StrategyA": Mock(),
        "StrategyB": Mock(),
        "StrategyC": Mock(),
        "StrategyD": Mock(),
    }


# ==================== JIT Identity Tests ====================

def test_generate_agent_identity(maestro):
    """Test JIT Identity generation."""
    identity = maestro.generate_agent_identity("TestStrategy")
    
    assert identity.agent_id == "test-tenant_TestStrategy"
    assert identity.strategy_name == "TestStrategy"
    assert len(identity.nonce) == 32  # 16 bytes = 32 hex chars
    assert identity.session_id == maestro.session_id
    assert isinstance(identity.timestamp, datetime)


def test_agent_identity_uniqueness(maestro):
    """Test that nonces are unique."""
    identities = [
        maestro.generate_agent_identity("Strategy1")
        for _ in range(100)
    ]
    
    nonces = [i.nonce for i in identities]
    assert len(set(nonces)) == len(nonces), "All nonces should be unique"


def test_agent_identity_to_dict(maestro):
    """Test AgentIdentity serialization."""
    identity = maestro.generate_agent_identity("TestStrategy")
    data = identity.to_dict()
    
    assert "agent_id" in data
    assert "strategy_name" in data
    assert "nonce" in data
    assert "timestamp" in data
    assert "session_id" in data
    assert isinstance(data["timestamp"], str)  # ISO format


# ==================== Performance Metrics Tests ====================

def test_calculate_performance_metrics_with_good_sharpe(maestro):
    """Test metrics calculation with positive returns."""
    daily_pnls = [100, 120, 110, 130, 125, 140, 135, 150, 145, 160]
    
    metrics = maestro._calculate_performance_metrics(
        strategy_name="TestStrategy",
        daily_pnls=daily_pnls,
        lookback_days=len(daily_pnls)
    )
    
    assert metrics.strategy_name == "TestStrategy"
    assert metrics.sharpe_ratio > 0  # Positive returns should have positive Sharpe
    assert metrics.total_return > 0
    assert metrics.data_points == len(daily_pnls)
    assert metrics.win_rate > 0


def test_calculate_performance_metrics_with_negative_sharpe(maestro):
    """Test metrics calculation with negative returns."""
    daily_pnls = [-50, -60, -40, -70, -55, -80, -65, -90, -75, -100]
    
    metrics = maestro._calculate_performance_metrics(
        strategy_name="TestStrategy",
        daily_pnls=daily_pnls,
        lookback_days=len(daily_pnls)
    )
    
    assert metrics.strategy_name == "TestStrategy"
    assert metrics.sharpe_ratio < 0  # Negative returns should have negative Sharpe
    assert metrics.total_return < 0
    assert metrics.win_rate == 0


def test_calculate_performance_metrics_with_insufficient_data(maestro):
    """Test metrics with insufficient data."""
    daily_pnls = [100]  # Only 1 data point
    
    metrics = maestro._calculate_performance_metrics(
        strategy_name="TestStrategy",
        daily_pnls=daily_pnls,
        lookback_days=len(daily_pnls)
    )
    
    assert metrics.sharpe_ratio == 0.0
    assert metrics.data_points == 1


def test_strategy_performance_is_healthy(maestro):
    """Test healthy strategy detection."""
    # Create healthy metrics
    healthy = StrategyPerformanceMetrics(
        strategy_name="Healthy",
        sharpe_ratio=1.5,
        annualized_return=0.25,
        daily_returns=[0.01, 0.02, 0.01, 0.015, 0.012],
        total_return=0.067,
        max_drawdown=-0.05,
        volatility=0.15,
        win_rate=0.8,
        data_points=10,
        last_updated=datetime.now(timezone.utc)
    )
    
    assert healthy.is_healthy() is True
    
    # Create unhealthy metrics (low Sharpe)
    unhealthy_sharpe = StrategyPerformanceMetrics(
        strategy_name="UnhealthySharpe",
        sharpe_ratio=0.3,
        annualized_return=0.05,
        daily_returns=[0.001] * 10,
        total_return=0.01,
        max_drawdown=-0.05,
        volatility=0.15,
        win_rate=0.6,
        data_points=10,
        last_updated=datetime.now(timezone.utc)
    )
    
    assert unhealthy_sharpe.is_healthy() is False
    
    # Create unhealthy metrics (large drawdown)
    unhealthy_dd = StrategyPerformanceMetrics(
        strategy_name="UnhealthyDD",
        sharpe_ratio=1.5,
        annualized_return=0.25,
        daily_returns=[0.01] * 10,
        total_return=0.1,
        max_drawdown=-0.6,  # 60% drawdown
        volatility=0.15,
        win_rate=0.8,
        data_points=10,
        last_updated=datetime.now(timezone.utc)
    )
    
    assert unhealthy_dd.is_healthy() is False


# ==================== Allocation Decision Tests ====================

@pytest.mark.asyncio
async def test_calculate_strategy_weights_no_data(maestro, mock_strategies):
    """Test weight calculation when no performance data is available."""
    # Mock empty Firestore results
    maestro.db = MockFirestoreClient()
    
    weights = await maestro.calculate_strategy_weights(mock_strategies)
    
    # All strategies should get default 1.0 weight with ACTIVE mode
    for strategy_name in mock_strategies.keys():
        weight, mode = weights[strategy_name]
        assert weight == 1.0
        assert mode == AgentMode.ACTIVE


@pytest.mark.asyncio
async def test_calculate_strategy_weights_with_good_performance(maestro, mock_strategies, mock_db):
    """Test weight calculation with good Sharpe ratios."""
    # Mock good performance data
    collection = mock_db.collection("tenants/test-tenant/strategy_performance")
    
    for strategy_name in mock_strategies.keys():
        for i in range(30):
            collection.add_mock_doc({
                "strategy_id": strategy_name,
                "period_start": datetime.now(timezone.utc) - timedelta(days=30-i),
                "realized_pnl": 100.0 + i * 10,  # Positive returns
                "unrealized_pnl": 50.0
            })
    
    maestro.db = mock_db
    weights = await maestro.calculate_strategy_weights(mock_strategies)
    
    # Should have allocation decisions
    assert hasattr(maestro, '_last_allocation_decisions')
    assert len(maestro._last_allocation_decisions) == len(mock_strategies)


@pytest.mark.asyncio
async def test_allocation_decision_modes(maestro):
    """Test different allocation modes based on Sharpe."""
    # Test ACTIVE mode (Sharpe >= 1.0)
    good_metrics = Mock()
    good_metrics.sharpe_ratio = 1.5
    good_metrics.is_healthy.return_value = True
    
    maestro._performance_cache["GoodStrategy"] = good_metrics
    maestro._cache_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    
    weights = await maestro.calculate_strategy_weights({"GoodStrategy": Mock()})
    weight, mode = weights["GoodStrategy"]
    
    assert mode == AgentMode.ACTIVE
    assert weight == 1.0
    
    # Test REDUCED mode (0.5 <= Sharpe < 1.0)
    ok_metrics = Mock()
    ok_metrics.sharpe_ratio = 0.8
    ok_metrics.is_healthy.return_value = True
    
    maestro._performance_cache["OkStrategy"] = ok_metrics
    
    weights = await maestro.calculate_strategy_weights({"OkStrategy": Mock()})
    weight, mode = weights["OkStrategy"]
    
    assert mode == AgentMode.REDUCED
    assert weight == 0.5
    
    # Test SHADOW mode (Sharpe < 0.5)
    bad_metrics = Mock()
    bad_metrics.sharpe_ratio = 0.3
    bad_metrics.is_healthy.return_value = True
    
    maestro._performance_cache["BadStrategy"] = bad_metrics
    
    weights = await maestro.calculate_strategy_weights({"BadStrategy": Mock()})
    weight, mode = weights["BadStrategy"]
    
    assert mode == AgentMode.SHADOW
    assert weight == 0.0


# ==================== Systemic Risk Tests ====================

def test_systemic_risk_no_override(maestro):
    """Test that no override occurs with insufficient SELL signals."""
    signals = {
        "A": {"action": "BUY"},
        "B": {"action": "BUY"},
        "C": {"action": "SELL"},
        "D": {"action": "SELL"},
    }
    
    modified, detected, details = maestro.apply_systemic_risk_override(signals)
    
    assert detected is False
    assert details is None
    assert modified == signals  # No modifications


def test_systemic_risk_with_override(maestro):
    """Test systemic risk override with 3+ SELL signals."""
    signals = {
        "A": {"action": "SELL"},
        "B": {"action": "SELL"},
        "C": {"action": "SELL"},
        "D": {"action": "BUY"},
        "E": {"action": "BUY"},
    }
    
    modified, detected, details = maestro.apply_systemic_risk_override(signals)
    
    assert detected is True
    assert details is not None
    assert "systemic risk" in details.lower()
    
    # BUY signals should be overridden to HOLD
    assert modified["D"]["action"] == "HOLD"
    assert modified["E"]["action"] == "HOLD"
    assert "override_reason" in modified["D"]
    assert "override_reason" in modified["E"]
    assert modified["D"]["confidence"] == 0.0
    
    # SELL signals should remain unchanged
    assert modified["A"]["action"] == "SELL"
    assert modified["B"]["action"] == "SELL"
    assert modified["C"]["action"] == "SELL"


def test_systemic_risk_exact_threshold(maestro):
    """Test systemic risk at exactly the threshold."""
    signals = {
        "A": {"action": "SELL"},
        "B": {"action": "SELL"},
        "C": {"action": "SELL"},  # Exactly 3 SELLs
        "D": {"action": "BUY"},
    }
    
    modified, detected, details = maestro.apply_systemic_risk_override(signals)
    
    # Should trigger at exactly 3 SELLs
    assert detected is True
    assert modified["D"]["action"] == "HOLD"


# ==================== Signal Enrichment Tests ====================

def test_enrich_signals_with_identity(maestro):
    """Test JIT Identity enrichment of signals."""
    signals = {
        "StrategyA": {"action": "BUY", "allocation": 0.5},
        "StrategyB": {"action": "SELL", "allocation": 0.3},
    }
    
    enriched = maestro.enrich_signals_with_identity(signals)
    
    # Check that all signals have identity
    for strategy_name, signal in enriched.items():
        assert "agent_id" in signal
        assert "nonce" in signal
        assert "session_id" in signal
        assert "identity_timestamp" in signal
        
        assert signal["agent_id"] == f"test-tenant_{strategy_name}"
        assert len(signal["nonce"]) == 32
        assert signal["session_id"] == maestro.session_id
    
    # Check that nonces are unique
    nonces = [s["nonce"] for s in enriched.values()]
    assert len(set(nonces)) == len(nonces)


def test_enrich_signals_preserves_data(maestro):
    """Test that enrichment preserves original signal data."""
    signals = {
        "Strategy1": {
            "action": "BUY",
            "allocation": 0.5,
            "ticker": "SPY",
            "reasoning": "Strong momentum",
            "confidence": 0.85
        }
    }
    
    enriched = maestro.enrich_signals_with_identity(signals)
    
    # Original data should be preserved
    assert enriched["Strategy1"]["action"] == "BUY"
    assert enriched["Strategy1"]["allocation"] == 0.5
    assert enriched["Strategy1"]["ticker"] == "SPY"
    assert enriched["Strategy1"]["reasoning"] == "Strong momentum"
    assert enriched["Strategy1"]["confidence"] == 0.85


# ==================== Orchestration Tests ====================

@pytest.mark.asyncio
async def test_full_orchestration(maestro, mock_strategies):
    """Test complete orchestration flow."""
    # Mock performance data (all strategies healthy)
    for strategy_name in mock_strategies.keys():
        metrics = Mock()
        metrics.sharpe_ratio = 1.5
        metrics.is_healthy.return_value = True
        maestro._performance_cache[strategy_name] = metrics
    
    maestro._cache_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Create test signals
    raw_signals = {
        "StrategyA": {"action": "BUY", "allocation": 0.5},
        "StrategyB": {"action": "SELL", "allocation": 0.3},
        "StrategyC": {"action": "BUY", "allocation": 0.4},
        "StrategyD": {"action": "HOLD", "allocation": 0.0},
    }
    
    # Mock AI summary generation to avoid Vertex AI calls
    with patch.object(maestro, 'generate_ai_summary', return_value="Test summary"):
        final_signals, decision = await maestro.orchestrate(
            signals=raw_signals,
            strategies=mock_strategies
        )
    
    # Verify orchestration results
    assert decision is not None
    assert isinstance(decision, MaestroDecision)
    assert decision.session_id == maestro.session_id
    
    # All signals should have JIT Identity
    for signal in final_signals.values():
        if isinstance(signal, dict):
            assert "agent_id" in signal
            assert "nonce" in signal
    
    # Check allocation decisions
    assert len(decision.allocation_decisions) == len(mock_strategies)


@pytest.mark.asyncio
async def test_orchestration_with_systemic_risk(maestro, mock_strategies):
    """Test orchestration with systemic risk override."""
    # Mock performance
    for strategy_name in mock_strategies.keys():
        metrics = Mock()
        metrics.sharpe_ratio = 1.5
        metrics.is_healthy.return_value = True
        maestro._performance_cache[strategy_name] = metrics
    
    maestro._cache_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Create signals with 3 SELLs (trigger systemic risk)
    raw_signals = {
        "StrategyA": {"action": "SELL", "allocation": 0.3},
        "StrategyB": {"action": "SELL", "allocation": 0.3},
        "StrategyC": {"action": "SELL", "allocation": 0.3},
        "StrategyD": {"action": "BUY", "allocation": 0.5},
    }
    
    with patch.object(maestro, 'generate_ai_summary', return_value="Risk override"):
        final_signals, decision = await maestro.orchestrate(
            signals=raw_signals,
            strategies=mock_strategies
        )
    
    # Verify systemic risk was detected
    assert decision.systemic_risk_detected is True
    assert decision.systemic_risk_details is not None
    
    # BUY signal should be overridden
    assert final_signals["StrategyD"]["action"] == "HOLD"
    assert "override_reason" in final_signals["StrategyD"]


# ==================== MaestroDecision Tests ====================

def test_maestro_decision_to_firestore_doc():
    """Test MaestroDecision serialization to Firestore format."""
    decision = MaestroDecision(
        timestamp=datetime.now(timezone.utc),
        session_id="test-session",
        systemic_risk_detected=True,
        systemic_risk_details="Test risk",
        ai_summary="Test summary"
    )
    
    decision.allocation_decisions.append(
        AllocationDecision(
            strategy_name="TestStrategy",
            original_allocation=1.0,
            final_allocation=0.5,
            mode=AgentMode.REDUCED,
            reasoning="Test reasoning",
            sharpe_ratio=0.8,
            timestamp=datetime.now(timezone.utc)
        )
    )
    
    doc = decision.to_firestore_doc()
    
    assert "timestamp" in doc
    assert "session_id" in doc
    assert "allocation_decisions" in doc
    assert "systemic_risk_detected" in doc
    assert "ai_summary" in doc
    
    # Check allocation decision format
    alloc = doc["allocation_decisions"][0]
    assert alloc["strategy_name"] == "TestStrategy"
    assert alloc["mode"] == "REDUCED"
    assert alloc["sharpe_ratio"] == 0.8


# ==================== Integration Tests ====================

@pytest.mark.asyncio
async def test_strategy_loader_with_maestro(mock_db):
    """Test StrategyLoader with Maestro integration."""
    loader = StrategyLoader(
        db=mock_db,
        tenant_id="test-tenant",
        uid="test-user"
    )
    
    assert loader.maestro is not None
    assert isinstance(loader.maestro, MaestroController)


@pytest.mark.asyncio
async def test_calculate_strategy_weights_on_loader(mock_db):
    """Test calculate_strategy_weights method on StrategyLoader."""
    loader = StrategyLoader(db=mock_db)
    
    # Should return default weights when no data
    weights = await loader.calculate_strategy_weights()
    
    assert isinstance(weights, dict)
    # All weights should be (1.0, "ACTIVE") by default
    for weight, mode in weights.values():
        assert weight == 1.0
        assert mode == "ACTIVE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
