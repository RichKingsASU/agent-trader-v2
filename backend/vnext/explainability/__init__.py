"""
vNEXT Explainability (schema-only)

This package defines the narrative schema used to explain decisions produced elsewhere in vNEXT.
It intentionally contains no business logic, I/O, or LLM integrations.
"""

from .interfaces import DecisionExplainer
from .schema import (
    ConfidenceStatement,
    ContributingFactors,
    DecisionNarrative,
)

__all__ = [
    "ConfidenceStatement",
    "ContributingFactors",
    "DecisionExplainer",
    "DecisionNarrative",
]

