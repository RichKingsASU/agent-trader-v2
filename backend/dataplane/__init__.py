"""
Vendor-neutral data plane scaffolding.

This package defines storage interfaces (tick/candle/proposal) and provides a
portable default implementation backed by partitioned NDJSON files.
"""

from __future__ import annotations

from .interfaces import CandleStore, NewsFeaturesProvider, ProposalStore, TickStore
from .file_store import FileCandleStore, FileProposalStore, FileTickStore, default_data_root
from .news_features import InMemoryNewsFeaturesProvider

__all__ = [
    "TickStore",
    "CandleStore",
    "ProposalStore",
    "NewsFeaturesProvider",
    "FileTickStore",
    "FileCandleStore",
    "FileProposalStore",
    "InMemoryNewsFeaturesProvider",
    "default_data_root",
]

