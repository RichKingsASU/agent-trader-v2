from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TenantContext:
    """
    Request-scoped identity.

    - uid: Firebase Auth uid (string)
    - tenant_id: tenant/org identifier (string)
    """

    uid: str
    tenant_id: str
    claims: Mapping[str, Any]

