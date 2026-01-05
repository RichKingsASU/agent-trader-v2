from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping, Optional


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


MarketplaceStrategyStatus = Literal["draft", "published", "suspended", "retired"]


@dataclass(frozen=True, slots=True)
class MarketplaceStrategy:
    """
    A global marketplace listing document.

    Firestore path:
      marketplace_strategies/{strategy_id}
    """

    strategy_id: str
    name: str
    status: MarketplaceStrategyStatus = "draft"

    description: Optional[str] = None
    tags: tuple[str, ...] = ()

    pricing: dict[str, Any] = field(default_factory=dict)
    publisher: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, Any] = field(default_factory=dict)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        sid = (self.strategy_id or "").strip()
        if not sid:
            raise ValueError("strategy_id is required")
        if "/" in sid:
            raise ValueError("strategy_id must not contain '/'")
        object.__setattr__(self, "strategy_id", sid)

        n = (self.name or "").strip()
        if not n:
            raise ValueError("name is required")
        object.__setattr__(self, "name", n)

        if self.status not in ("draft", "published", "suspended", "retired"):
            raise ValueError("status must be one of: draft|published|suspended|retired")

        if self.description is not None:
            object.__setattr__(self, "description", str(self.description))

        # Normalize tags.
        normalized_tags: list[str] = []
        for t in self.tags or ():
            s = str(t).strip()
            if not s:
                continue
            normalized_tags.append(s)
        object.__setattr__(self, "tags", tuple(normalized_tags))

        if self.created_at is not None:
            object.__setattr__(self, "created_at", _as_utc(self.created_at))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _as_utc(self.updated_at))

    def to_firestore(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "status": self.status,
        }
        if self.description is not None:
            doc["description"] = self.description
        if self.tags:
            doc["tags"] = list(self.tags)
        if self.pricing:
            doc["pricing"] = dict(self.pricing)
        if self.publisher:
            doc["publisher"] = dict(self.publisher)
        if self.visibility:
            doc["visibility"] = dict(self.visibility)
        if self.created_at is not None:
            doc["created_at"] = self.created_at
        if self.updated_at is not None:
            doc["updated_at"] = self.updated_at
        return doc

    @staticmethod
    def from_firestore(strategy_id: str, data: Mapping[str, Any]) -> "MarketplaceStrategy":
        d = dict(data or {})
        # Prefer explicit stored id; otherwise use doc id.
        sid = str(d.get("strategy_id") or strategy_id or "").strip()
        tags: Iterable[str] = d.get("tags") or ()
        return MarketplaceStrategy(
            strategy_id=sid,
            name=str(d.get("name") or "").strip(),
            status=str(d.get("status") or "draft"),
            description=d.get("description"),
            tags=tuple(str(t) for t in tags),
            pricing=dict(d.get("pricing") or {}),
            publisher=dict(d.get("publisher") or {}),
            visibility=dict(d.get("visibility") or {}),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


@dataclass(frozen=True, slots=True)
class StrategySubscription:
    """
    Tenant-scoped subscription document linking a user to a marketplace strategy.

    Firestore path:
      tenants/{tid}/subscriptions/{sub_id}
    """

    tenant_id: str
    uid: str
    strategy_id: str

    start_at: datetime
    end_at: Optional[datetime] = None
    active: bool = True

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        tid = (self.tenant_id or "").strip()
        if not tid:
            raise ValueError("tenant_id is required")
        if "/" in tid:
            raise ValueError("tenant_id must not contain '/'")
        object.__setattr__(self, "tenant_id", tid)

        u = (self.uid or "").strip()
        if not u:
            raise ValueError("uid is required")
        if "/" in u:
            raise ValueError("uid must not contain '/'")
        object.__setattr__(self, "uid", u)

        sid = (self.strategy_id or "").strip()
        if not sid:
            raise ValueError("strategy_id is required")
        if "/" in sid:
            raise ValueError("strategy_id must not contain '/'")
        object.__setattr__(self, "strategy_id", sid)

        object.__setattr__(self, "start_at", _as_utc(self.start_at))
        if self.end_at is not None:
            end_utc = _as_utc(self.end_at)
            object.__setattr__(self, "end_at", end_utc)
            if end_utc <= self.start_at:
                raise ValueError("end_at must be > start_at")

        if self.created_at is not None:
            object.__setattr__(self, "created_at", _as_utc(self.created_at))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _as_utc(self.updated_at))

    def to_firestore(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "uid": self.uid,
            "strategy_id": self.strategy_id,
            "start_at": self.start_at,
            "active": bool(self.active),
        }
        if self.end_at is not None:
            doc["end_at"] = self.end_at
        if self.created_at is not None:
            doc["created_at"] = self.created_at
        if self.updated_at is not None:
            doc["updated_at"] = self.updated_at
        return doc

    @staticmethod
    def from_firestore(*, tenant_id: str, data: Mapping[str, Any]) -> "StrategySubscription":
        d = dict(data or {})
        return StrategySubscription(
            tenant_id=str(d.get("tenant_id") or tenant_id or "").strip(),
            uid=str(d.get("uid") or "").strip(),
            strategy_id=str(d.get("strategy_id") or "").strip(),
            start_at=d.get("start_at"),
            end_at=d.get("end_at"),
            active=bool(d.get("active", True)),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

