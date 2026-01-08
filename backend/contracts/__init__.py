"""
Shared, versioned contracts for cross-agent/service interactions.

Rule of thumb:
- Services OWN behavior/handlers.
- Contracts OWN schemas (request/response payload shapes).

Import these contracts from both producers and consumers to prevent drift.
"""

