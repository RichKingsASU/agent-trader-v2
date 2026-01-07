# Strategy Contracts (Schema-first Enforcement)

This module enforces **explicit strategy declarations** via a schema-first **Strategy Contract**.

## Core rule: no implicit data consumption

Strategies **cannot implicitly consume data**. A strategy must declare, in its contract:

- `required_features`: the data/features it consumes (e.g. `OHLCV`, `OPTIONS_CHAIN`, `NEWS`).
- `capabilities`: what it can do (e.g. `GENERATE_TRADE_PROPOSALS`, `EXECUTE_TRADES`).
- `allowed_agent_modes`: which global authority modes it is permitted to run under.

Empty lists are allowed (e.g. `required_features: []`), but the fields must be present.

## Capabilities are validated before promotion

Before a strategy is promoted to higher privilege (e.g. allowed to execute), the platform should:

- load and validate the strategy contract
- block promotion if the contract is missing or invalid
- ensure execution-related capabilities imply `allowed_agent_modes` includes `LIVE`

This keeps “what the strategy may do” reviewable and enforceable **before** runtime enablement.

## Where contracts live

By default, contracts are read from:

- `configs/strategies/contracts/<strategy_id>.yaml` (or `.yml` / `.json`)

Override with:

- `STRATEGY_CONTRACT_DIR=/abs/or/relative/path`

## Public interface

- `validate_strategy_contract(strategy_id)`: loads + validates the contract (fail-closed).

