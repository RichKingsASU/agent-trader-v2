# Portfolio Risk (vNEXT)

This module defines **read-only**, **strategy-agnostic** portfolio-level risk data models.

## Principles

- **Read-only**: outputs describe exposures/risks and MUST NOT trigger trades or execution.
- **Strategy-agnostic**: callers may compute inputs from any source (broker, ledger, backtests, mocks).

## What’s included

- Data models for exposure snapshots, concentration metrics, and correlation risk summaries.
- A provider interface (`get_portfolio_risk()`) that returns an aggregated risk report.

