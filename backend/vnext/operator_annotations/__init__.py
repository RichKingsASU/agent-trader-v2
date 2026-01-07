"""
Operator annotations & overrides (vNEXT).

This package defines audit-friendly, non-executing scaffolding for human/operator
notes and advisory overrides.
"""

from .interfaces import OperatorOverridesProvider
from .models import AnnotationScope, OperatorNote, OverrideReason

__all__ = [
    "AnnotationScope",
    "OperatorNote",
    "OperatorOverridesProvider",
    "OverrideReason",
]

