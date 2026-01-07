# vNEXT Signal Freshness (Contracts)

This package defines **contracts only** for how signal freshness is represented and queried.

## Strategy requirements

- **Down-weight or refuse stale signals**: Strategies must explicitly handle `DEGRADED` and `STALE` states.
  - `DEGRADED` signals must be down-weighted (or otherwise risk-adjusted).
  - `STALE` signals must be refused (or treated as a hard constraint violation).
- **No silent staleness allowed**: Missing/unknown freshness must **not** be treated as usable-by-default.
  - If freshness cannot be determined, implementations must surface this as `STALE` (or the configured equivalent),
    never as `FRESH`.

## Interfaces

See `interfaces.py` for:

- `SignalTimestamp`
- `FreshnessPolicy`
- `StalenessState` (`FRESH` / `DEGRADED` / `STALE`)
- `SignalFreshness.get_signal_state(signal_name)`

