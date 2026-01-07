"""
Deterministic news -> strategy-safe feature extraction.

This module is intentionally rules-based (no LLM calls) to ensure:
- deterministic output for same input
- low operational risk
"""

from .models import EventType, NewsFeatureRecord
from .analyzer import classify_event, relevance, sentiment, to_feature_records

__all__ = [
    "EventType",
    "NewsFeatureRecord",
    "sentiment",
    "classify_event",
    "relevance",
    "to_feature_records",
]

