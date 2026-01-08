"""
Handler package.

Handlers must be:
- idempotent (writer enforces overwrite-only-if-newer)
- tolerant to missing fields (producers are not modified)
"""

