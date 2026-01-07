# Social & Community Intelligence (vNEXT) — Deferred by Design

This module defines **interfaces and governance constraints only**. It exists to make *social signal awareness* explicit in the architecture while **deferring any collection, ingestion, or scoring implementation** until it can be reviewed under compliance, privacy, security, and platform ToS requirements.

## Scope (explicitly allowed sources)

- **Discord bot only (permissioned)**: Signals may be produced **only** from Discord servers/channels where the bot has been explicitly invited and authorized, and where required permissions have been granted.
- **Reddit API only**: Signals may be produced **only** via official Reddit API access, within policy and rate limits.

## Explicit non-goals (hard prohibitions)

- **No crawling**
- **No scraping**
- No bypassing authentication / paywalls / private communities
- No collection of personal data beyond what is strictly necessary for anti-spam and deduplication (prefer hashed/opaque identifiers)
- No storing of raw message bodies by default (prefer hashes, aggregates, short excerpts when essential)

## Governance framing (why this is interface-only)

Social data can be high-impact, high-noise, and policy-sensitive. This architecture:

- Treats social signals as **risk context**, not alpha by default.
- Requires **auditability** (rationales and inputs must be explainable).
- Enforces **data minimization** and **purpose limitation** (risk awareness only).
- Separates collection from strategy logic so strategies remain deterministic and avoid network I/O.
- Avoids “silent scope creep”: adding a new source requires an explicit code change and review.

## What exists today

- `interfaces.py` defines:
  - `SocialMention`
  - `SocialVelocitySignal`
  - `CredibilityScore`
  - `SocialRiskProvider.get_social_risk(symbol)`

## What does NOT exist yet (by design)

- No ingestion workers
- No Discord bot implementation
- No Reddit client implementation
- No production scoring model
- No storage schema

