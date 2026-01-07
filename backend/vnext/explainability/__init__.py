"""
vNEXT Explainability — Narrative schema (contracts only).

This package defines data-only narrative explanations for decisions.

See `backend/vnext/GOVERNANCE.md` for cross-cutting invariants.
"""

from .interfaces import (  # noqa: F401
    ConfidenceStatement,
    ContributingFactors,
    DecisionNarrative,
    explain_decision,
)

