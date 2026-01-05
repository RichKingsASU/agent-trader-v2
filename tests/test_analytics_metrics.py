"""
Tests for the metrics tracking system.
"""

import pytest
from datetime import datetime, timezone
import time

from backend.analytics.metrics import (
    MetricsTracker,
    get_metrics_tracker,
    track_api_call,
)


@pytest.fixture
def tracker():
    """Create a fresh metrics tracker for each test"""
    return MetricsTracker(retention_minutes=60)


def test_record_api_call(tracker):
    """Test recording an API call metric"""
    tracker.record_api_call(
        service="alpaca",
        endpoint="/v2/account",
        duration_ms=250.5,
        status="success",
    )
    
    assert len(tracker.api_metrics) == 1
    metric = tracker.api_metrics[0]
    
    assert metric.service == "alpaca"
    assert metric.endpoint == "/v2/account"
    assert metric.duration_ms == 250.5
    assert metric.status == "success"
    assert metric.error_message is None


def test_record_api_call_with_error(tracker):
    """Test recording a failed API call"""
    tracker.record_api_call(
        service="gemini",
        endpoint="/generate",
        duration_ms=1500.0,
        status="error",
        error_message="Rate limit exceeded",
    )
    
    metric = tracker.api_metrics[0]
    
    assert metric.status == "error"
    assert metric.error_message == "Rate limit exceeded"


def test_record_token_usage(tracker):
    """Test recording token usage"""
    tracker.record_token_usage(
        user_id="user123",
        model="gemini-2.5-flash",
        prompt_tokens=1000,
        completion_tokens=500,
        request_type="signal_generation",
    )
    
    assert len(tracker.token_metrics) == 1
    metric = tracker.token_metrics[0]
    
    assert metric.user_id == "user123"
    assert metric.model == "gemini-2.5-flash"
    assert metric.prompt_tokens == 1000
    assert metric.completion_tokens == 500
    assert metric.total_tokens == 1500
    assert metric.cost_estimate > 0  # Should calculate cost


def test_get_api_latency_stats(tracker):
    """Test retrieving API latency statistics"""
    # Record multiple calls
    for duration in [100, 200, 300, 400, 500]:
        tracker.record_api_call(
            service="alpaca",
            endpoint="/v2/orders",
            duration_ms=float(duration),
        )
    
    stats = tracker.get_api_latency_stats("alpaca", minutes=60)
    
    assert stats["count"] == 5
    assert stats["avg_ms"] == 300.0
    assert stats["min_ms"] == 100.0
    assert stats["max_ms"] == 500.0
    assert stats["p50_ms"] == 300.0
    assert stats["error_rate"] == 0.0


def test_get_api_latency_stats_with_errors(tracker):
    """Test latency stats with error rate calculation"""
    # 3 successful, 2 errors
    for i in range(3):
        tracker.record_api_call(
            service="gemini",
            endpoint="/generate",
            duration_ms=800.0,
            status="success",
        )
    
    for i in range(2):
        tracker.record_api_call(
            service="gemini",
            endpoint="/generate",
            duration_ms=1000.0,
            status="error",
        )
    
    stats = tracker.get_api_latency_stats("gemini", minutes=60)
    
    assert stats["count"] == 5
    assert stats["error_rate"] == 40.0  # 2/5 * 100


def test_get_token_usage_by_user(tracker):
    """Test retrieving token usage for a specific user"""
    # Record multiple requests
    for i in range(3):
        tracker.record_token_usage(
            user_id="user123",
            model="gemini-2.5-flash",
            prompt_tokens=1000,
            completion_tokens=500,
            request_type="signal_generation",
        )
    
    usage = tracker.get_token_usage_by_user("user123", hours=24)
    
    assert usage["total_requests"] == 3
    assert usage["total_tokens"] == 4500  # 1500 * 3
    assert usage["prompt_tokens"] == 3000
    assert usage["completion_tokens"] == 1500
    assert usage["avg_tokens_per_request"] == 1500.0


def test_get_all_users_token_usage(tracker):
    """Test retrieving token usage for all users"""
    # Record usage for multiple users
    tracker.record_token_usage(
        user_id="user1",
        model="gemini-2.5-flash",
        prompt_tokens=2000,
        completion_tokens=1000,
    )
    
    tracker.record_token_usage(
        user_id="user2",
        model="gemini-2.5-flash",
        prompt_tokens=5000,
        completion_tokens=2000,
    )
    
    all_usage = tracker.get_all_users_token_usage(hours=24)
    
    assert len(all_usage) == 2
    # Should be sorted by cost (user2 has higher usage)
    assert all_usage[0]["user_id"] == "user2"
    assert all_usage[1]["user_id"] == "user1"


def test_track_api_call_context_manager():
    """Test the track_api_call context manager"""
    tracker = get_metrics_tracker()
    initial_count = len(tracker.api_metrics)
    
    with track_api_call("alpaca", "/v2/account"):
        time.sleep(0.05)  # Simulate API call
    
    assert len(tracker.api_metrics) == initial_count + 1
    metric = tracker.api_metrics[-1]
    
    assert metric.service == "alpaca"
    assert metric.endpoint == "/v2/account"
    assert metric.duration_ms >= 50  # At least 50ms
    assert metric.status == "success"


def test_track_api_call_with_exception():
    """Test context manager with an exception"""
    tracker = get_metrics_tracker()
    initial_count = len(tracker.api_metrics)
    
    with pytest.raises(ValueError):
        with track_api_call("gemini", "/generate"):
            raise ValueError("Test error")
    
    assert len(tracker.api_metrics) == initial_count + 1
    metric = tracker.api_metrics[-1]
    
    assert metric.status == "error"
    assert metric.error_message == "Test error"


def test_metrics_cleanup(tracker):
    """Test that old metrics are cleaned up"""
    # Set very short retention
    tracker.retention_minutes = 0.001  # ~0.06 seconds
    
    tracker.record_api_call(
        service="alpaca",
        endpoint="/test",
        duration_ms=100.0,
    )
    
    assert len(tracker.api_metrics) == 1
    
    # Wait for retention period to expire
    time.sleep(0.1)
    
    # Record another call to trigger cleanup
    tracker.record_api_call(
        service="alpaca",
        endpoint="/test",
        duration_ms=100.0,
    )
    
    # Old metric should be cleaned up
    assert len(tracker.api_metrics) == 1


def test_token_cost_calculation(tracker):
    """Test that token cost is calculated correctly"""
    tracker.record_token_usage(
        user_id="user123",
        model="gemini-2.5-flash",
        prompt_tokens=1_000_000,  # 1M tokens
        completion_tokens=1_000_000,  # 1M tokens
    )
    
    metric = tracker.token_metrics[0]
    
    # Expected cost: (1M * 0.075 / 1M) + (1M * 0.30 / 1M) = 0.075 + 0.30 = 0.375
    assert abs(metric.cost_estimate - 0.375) < 0.001
