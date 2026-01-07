"""
Execution Agent (paper-only stub, NO real orders).

This service:
- consumes OrderProposals (NDJSON)
- applies safety/risk preflight
- emits ExecutionDecision audit artifacts

It never calls broker APIs and is hard-gated at startup.
"""

