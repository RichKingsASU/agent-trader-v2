from __future__ import annotations

from typing import Protocol

from .schema import DecisionNarrative


class DecisionExplainer(Protocol):
    """
    Interface for producing a narrative explanation for a decision.

    Implementations should be pure/side-effect free and fetch required inputs via injected adapters.
    """

    def explain_decision(self, decision_id: str) -> DecisionNarrative:
        """
        Produce a `DecisionNarrative` for the given decision id.
        """

