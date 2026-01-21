"""
Observer explanation persistence utilities.

This package is intentionally read/write ONLY for local explanation artifacts.
It does not perform any database writes (no Firestore, no SQL).
"""

from .models import ExplanationRecord
from .storage import ExplanationStorage, get_default_storage

__all__ = [
    "ExplanationRecord",
    "ExplanationStorage",
    "get_default_storage",
]

