"""
Back-compat wrapper for the centralized config system.

New code should import from:
- backend.common.config

This module remains to avoid changing older entrypoints.
"""

from __future__ import annotations

from typing import Mapping


def validate_or_exit(service: str, *, env: Mapping[str, str] | None = None) -> None:  # type: ignore[no-redef]
    # Wrapper kept for import compatibility.
    from backend.common.config import validate_or_exit as _impl

    _impl(service, env=env)

