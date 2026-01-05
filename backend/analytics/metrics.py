"""
System Metrics Tracking

Tracks API latency, token usage, and system health metrics for monitoring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from contextlib import contextmanager


@dataclass
class APICallMetric:
    """Metric for a single API call"""
    
    service: str  # "alpaca" or "gemini"
    endpoint: str  # API endpoint called
    duration_ms: float  # Duration in milliseconds
    timestamp: datetime
    status: str = "success"  # "success", "error", "timeout"
    error_message: Optional[str] = None


@dataclass
class TokenUsageMetric:
    """Metric for Gemini token usage"""
    
    user_id: str
    model: str  # e.g., "gemini-2.5-flash"
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: datetime
    request_type: str = "signal_generation"  # Type of AI request
    cost_estimate: float = 0.0  # Estimated cost in USD


@dataclass
class SystemHealthSnapshot:
    """Snapshot of system health metrics"""
    
    timestamp: datetime
    alpaca_latency_avg_ms: float
    alpaca_latency_p95_ms: float
    alpaca_error_rate: float
    gemini_latency_avg_ms: float
    gemini_latency_p95_ms: float
    gemini_error_rate: float
    heartbeat_status: str  # "healthy", "degraded", "down"
    heartbeat_last_seen: Optional[datetime]
    active_users: int = 0
    total_requests_1h: int = 0


class MetricsTracker:
    """
    In-memory metrics tracker for system monitoring.
    
    Note: For production, this should be backed by a time-series database
    like Prometheus, InfluxDB, or Cloud Monitoring.
    """
    
    def __init__(self, retention_minutes: int = 60):
        self.retention_minutes = retention_minutes
        self.api_metrics: List[APICallMetric] = []
        self.token_metrics: List[TokenUsageMetric] = []
        self._lock = None  # Add threading lock in production
    
    def record_api_call(
        self,
        service: str,
        endpoint: str,
        duration_ms: float,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """Record an API call metric"""
        metric = APICallMetric(
            service=service,
            endpoint=endpoint,
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc),
            status=status,
            error_message=error_message,
        )
        self.api_metrics.append(metric)
        self._cleanup_old_metrics()
    
    def record_token_usage(
        self,
        user_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        request_type: str = "signal_generation",
    ) -> None:
        """Record Gemini token usage"""
        total_tokens = prompt_tokens + completion_tokens
        
        # Estimate cost (approximate rates for Gemini 2.5 Flash as of Dec 2024)
        # Input: $0.075 per 1M tokens, Output: $0.30 per 1M tokens
        cost = (prompt_tokens * 0.075 / 1_000_000) + (completion_tokens * 0.30 / 1_000_000)
        
        metric = TokenUsageMetric(
            user_id=user_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            timestamp=datetime.now(timezone.utc),
            request_type=request_type,
            cost_estimate=cost,
        )
        self.token_metrics.append(metric)
        self._cleanup_old_metrics()
    
    def get_api_latency_stats(
        self,
        service: str,
        minutes: int = 15,
    ) -> Dict[str, float]:
        """Get latency statistics for a service"""
        cutoff = datetime.now(timezone.utc).timestamp() - (minutes * 60)
        
        recent_metrics = [
            m for m in self.api_metrics
            if m.service == service and m.timestamp.timestamp() > cutoff
        ]
        
        if not recent_metrics:
            return {
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "count": 0,
                "error_rate": 0.0,
            }
        
        durations = sorted([m.duration_ms for m in recent_metrics])
        errors = sum(1 for m in recent_metrics if m.status == "error")
        
        return {
            "avg_ms": sum(durations) / len(durations),
            "min_ms": durations[0],
            "max_ms": durations[-1],
            "p50_ms": durations[len(durations) // 2],
            "p95_ms": durations[int(len(durations) * 0.95)],
            "p99_ms": durations[int(len(durations) * 0.99)],
            "count": len(durations),
            "error_rate": (errors / len(recent_metrics)) * 100,
        }
    
    def get_token_usage_by_user(
        self,
        user_id: str,
        hours: int = 24,
    ) -> Dict[str, any]:
        """Get token usage summary for a user"""
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        
        user_metrics = [
            m for m in self.token_metrics
            if m.user_id == user_id and m.timestamp.timestamp() > cutoff
        ]
        
        if not user_metrics:
            return {
                "total_requests": 0,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_cost": 0.0,
                "avg_tokens_per_request": 0.0,
            }
        
        total_tokens = sum(m.total_tokens for m in user_metrics)
        prompt_tokens = sum(m.prompt_tokens for m in user_metrics)
        completion_tokens = sum(m.completion_tokens for m in user_metrics)
        total_cost = sum(m.cost_estimate for m in user_metrics)
        
        return {
            "total_requests": len(user_metrics),
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_cost": total_cost,
            "avg_tokens_per_request": total_tokens / len(user_metrics),
        }
    
    def get_all_users_token_usage(
        self,
        hours: int = 24,
    ) -> List[Dict[str, any]]:
        """Get token usage for all users, sorted by cost"""
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        
        recent_metrics = [
            m for m in self.token_metrics
            if m.timestamp.timestamp() > cutoff
        ]
        
        # Group by user
        user_stats: Dict[str, Dict[str, any]] = {}
        for metric in recent_metrics:
            if metric.user_id not in user_stats:
                user_stats[metric.user_id] = {
                    "user_id": metric.user_id,
                    "total_requests": 0,
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_cost": 0.0,
                }
            
            stats = user_stats[metric.user_id]
            stats["total_requests"] += 1
            stats["total_tokens"] += metric.total_tokens
            stats["prompt_tokens"] += metric.prompt_tokens
            stats["completion_tokens"] += metric.completion_tokens
            stats["total_cost"] += metric.cost_estimate
        
        # Sort by cost descending
        return sorted(
            user_stats.values(),
            key=lambda x: x["total_cost"],
            reverse=True,
        )
    
    def _cleanup_old_metrics(self) -> None:
        """Remove metrics older than retention period"""
        cutoff = datetime.now(timezone.utc).timestamp() - (self.retention_minutes * 60)
        
        self.api_metrics = [
            m for m in self.api_metrics
            if m.timestamp.timestamp() > cutoff
        ]
        
        self.token_metrics = [
            m for m in self.token_metrics
            if m.timestamp.timestamp() > cutoff
        ]


# Global singleton instance
_global_tracker: Optional[MetricsTracker] = None


def get_metrics_tracker() -> MetricsTracker:
    """Get or create the global metrics tracker instance"""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = MetricsTracker(retention_minutes=60)
    return _global_tracker


@contextmanager
def track_api_call(service: str, endpoint: str):
    """
    Context manager to track API call duration.
    
    Usage:
        with track_api_call("alpaca", "/v2/account"):
            response = alpaca_client.get_account()
    """
    tracker = get_metrics_tracker()
    start_time = time.time()
    error_msg = None
    status = "success"
    
    try:
        yield
    except Exception as e:
        status = "error"
        error_msg = str(e)
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        tracker.record_api_call(
            service=service,
            endpoint=endpoint,
            duration_ms=duration_ms,
            status=status,
            error_message=error_msg,
        )
