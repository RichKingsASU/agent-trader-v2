# Feature Registry (vNEXT)

This directory defines the **canonical registry** for all features/signals used across the system:
**price**, **volatility**, **macro**, **news**, **social**, and **regime**.

It provides:

- **Schemas**: `FeatureDefinition`, `FeatureVersion`, `FeatureCategory` in `models.py`
- **Registry interface**: `get_feature(name)` and `list_features(category=None)` in `registry.py`

---

## Governance rules (canonical)

- **Features are immutable once published**
  - A published feature is identified by the pair `(name, version)`, written as `name@version`.
  - A previously published `name@version` **must never change** (schema, semantics, units, frequency, lineage).
  - The registry enforces this by refusing to overwrite an existing `(name, version)` entry.

- **Breaking changes require a new version**
  - Any change that could alter downstream behavior is a breaking change, including:
    - Different computation/definition (semantic meaning changes)
    - Output type changes (`value_type`, shape/encoding)
    - Units/frequency changes
    - Lookback/window changes that materially alter distribution
    - Dependency/lineage changes that alter meaning (not just implementation optimization)
  - Publish the breaking change as a **new version** (e.g. `price.close@2.0.0`).

- **Strategies may only consume registered features**
  - Strategy configs and strategy code must reference features via the registry (never ad-hoc field names).
  - For reproducibility, strategies should pin explicit versions (use `name@version`) rather than relying on implicit “latest”.

---

## Naming conventions

- **`name` is stable and versionless**, e.g.:
  - `price.close`
  - `vol.realized_20d`
  - `macro.cpi_yoy`
  - `news.sentiment_aggregate_1d`
  - `social.reddit.volume_zscore`
  - `regime.risk_on_probability`

Recommendation:

- Use `<domain>.<noun_or_metric>[_<qualifier>]`
- Keep names lowercase with `.` separators
- Treat renames as **new features** (do not mutate old names)

---

## How to use the interface

- **Get a feature**
  - Use explicit version: `get_feature("price.close@1.0.0")`
  - If only one version exists for a base name, `get_feature("price.close")` returns it.
  - If multiple versions exist, `get_feature("price.close")` raises and instructs you to pin.

- **List features**
  - `list_features()` returns all registered features (all versions).
  - `list_features(category=FeatureCategory.MACRO)` filters by category.

