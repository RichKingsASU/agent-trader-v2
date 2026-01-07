from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import FeatureCategory, FeatureDefinition


def _version_key(v: str) -> tuple[int, int, int, str]:
    """
    Best-effort semantic-ish version sort key.

    Examples:
      - "1.2.3" -> (1,2,3,"")
      - "1.2" -> (1,2,0,"")
      - "1.2.3-rc1" -> (1,2,3,"-rc1")

    This is intentionally lightweight and avoids extra dependencies.
    """

    core, sep, suffix = v.partition("-")
    parts = core.split(".")
    nums: list[int] = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2], (sep + suffix) if sep else "")


@dataclass(slots=True)
class FeatureRegistry:
    """
    In-memory canonical registry of published features.

    Storage layout: name -> version -> FeatureDefinition
    """

    _features: dict[str, dict[str, FeatureDefinition]] = field(default_factory=dict)

    def register(self, feature: FeatureDefinition) -> None:
        """
        Register a published feature definition.

        This enforces immutability at the registry level by disallowing overwrites
        of an existing (name, version) pair.
        """

        name = feature.name
        ver = feature.version.version
        versions = self._features.setdefault(name, {})
        if ver in versions:
            raise ValueError(f'Feature already registered: "{name}@{ver}"')
        versions[ver] = feature

    def get_feature(self, name: str) -> FeatureDefinition:
        """
        Fetch a feature by identifier.

        - If `name` is "base@version", returns that exact version.
        - If `name` is "base" and only one version exists, returns it.
        - If `name` is "base" and multiple versions exist, raises KeyError.
        """

        base, at, ver = name.partition("@")
        if base not in self._features:
            raise KeyError(f'Unknown feature: "{base}"')
        versions = self._features[base]
        if at:
            if ver not in versions:
                raise KeyError(f'Unknown feature version: "{base}@{ver}"')
            return versions[ver]
        if len(versions) == 1:
            return next(iter(versions.values()))
        available = ", ".join(sorted(versions.keys(), key=_version_key))
        raise KeyError(
            f'Ambiguous feature "{base}" (available versions: {available}). '
            "Use the explicit form base@version."
        )

    def list_features(self, category: Optional[FeatureCategory] = None) -> list[FeatureDefinition]:
        """
        List all registered feature definitions.

        If `category` is provided, filters to that category.
        """

        out: list[FeatureDefinition] = []
        for name in sorted(self._features.keys()):
            versions = self._features[name]
            for ver in sorted(versions.keys(), key=_version_key):
                feat = versions[ver]
                if category is None or feat.category == category:
                    out.append(feat)
        return out


# Default module-level registry + required interface functions.
_DEFAULT_REGISTRY = FeatureRegistry()


def register_feature(feature: FeatureDefinition) -> None:
    _DEFAULT_REGISTRY.register(feature)


def get_feature(name: str) -> FeatureDefinition:
    return _DEFAULT_REGISTRY.get_feature(name)


def list_features(category: Optional[FeatureCategory] = None) -> list[FeatureDefinition]:
    return _DEFAULT_REGISTRY.list_features(category)

