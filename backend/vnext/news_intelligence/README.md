## News Intelligence (vNEXT) — Non-Operational

This module defines **interfaces and data contracts only** for a compliant news intelligence layer. It intentionally **does not** include ingestion, storage, polling, scraping, or strategy/execution wiring.

### Governance requirements

- **Approved sources only**
  - Implementations MUST use **licensed/contracted** sources that your organization has approved (e.g., a paid vendor API or a broker-provided licensed feed).
  - Maintain an internal **allowlist** of permitted sources and reject anything outside that allowlist.
  - Preserve **traceability** (e.g., `source`, `id`, `url`, timestamps) to support audits and vendor compliance.

- **No scraping**
  - Do **not** scrape websites, RSS pages that prohibit automated use, or any content that violates terms of service.
  - Do **not** bypass paywalls, robots directives, or access controls.
  - If the source is not explicitly licensed/approved, it is **out of scope**.

- **No direct trade triggers**
  - News items and derived events are **not** trading signals.
  - Do **not** wire `get_recent_news()` outputs directly into order placement, position sizing, or execution decisions.
  - If news is used downstream, it must be mediated through a **separately reviewed** feature extraction / risk gating layer and should be treated as informational inputs only.

### Interfaces

Defined in `interfaces.py`:

- `NewsItem`: a single licensed news artifact (article / press release / bulletin).
- `NewsEvent`: a normalized event derived from one or more `NewsItem`s (optional, analysis-friendly).
- `NewsConfidence`: coarse confidence labels for derived events.
- `NewsIntelligenceProvider.get_recent_news(symbol, lookback_minutes)`: read-only retrieval contract.

