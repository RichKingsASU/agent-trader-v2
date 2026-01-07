"""
Canonical registry for all signals/features.

This package defines the feature schemas and a minimal registry interface.
Governance rules live in `README.md` in this directory.
"""

from .models import FeatureCategory, FeatureDefinition, FeatureVersion
from .registry import FeatureRegistry, get_feature, list_features, register_feature

__all__ = [
    "FeatureCategory",
    "FeatureDefinition",
    "FeatureRegistry",
    "FeatureVersion",
    "get_feature",
    "list_features",
    "register_feature",
]

