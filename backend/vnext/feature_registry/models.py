from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FeatureCategory(str, Enum):
    PRICE = "PRICE"
    VOL = "VOL"
    MACRO = "MACRO"
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"
    REGIME = "REGIME"


@dataclass(frozen=True, slots=True)
class FeatureVersion:
    """
    Version metadata for a published feature.

    `version` should be semantic-version-like (e.g. "1.0.0"). Once published, a
    version is immutable (enforced via frozen dataclass).
    """

    version: str
    published_at_utc: Optional[datetime] = None
    git_sha: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """
    Canonical feature contract.

    A feature is identified by a stable, versionless `name` (e.g. "price.close").
    A specific published artifact is identified by (name, version.version).
    """

    # Identity
    name: str
    category: FeatureCategory
    version: FeatureVersion

    # Contract
    description: str
    value_type: str
    unit: Optional[str] = None
    frequency: Optional[str] = None

    # Lineage / deps
    inputs: tuple[str, ...] = field(default_factory=tuple)

    # Metadata
    owner: Optional[str] = None
    source: Optional[str] = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Normalize possibly-mutable inputs/tags into immutable tuples.
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "tags", tuple(self.tags))

