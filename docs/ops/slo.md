## AgentTrader v2 — SLOs (simple, meaningful, safety-aligned)

These SLOs focus on **freshness**, **continuity**, and **basic availability** (not execution outcomes).

### SLO 1 — Marketdata freshness (market hours)

- **Objective**: **99%** of minutes during market hours have `heartbeat_age_seconds < 120`.
- **Rationale**: strategies are only as good as their upstream data freshness; stale data is a primary safety signal.
- **Signal**: `heartbeat_age_seconds` (Prometheus metric; exported by `marketdata-mcp-server`)
- **Suggested threshold**: 120s (tune via `MARKETDATA_STALE_THRESHOLD_S`)

**How to measure (PromQL example):**

```text
sum_over_time((heartbeat_age_seconds < 120)[1d:1m])
/
count_over_time(heartbeat_age_seconds[1d:1m])
```

**Market-hours scoping**: if you need a strict market-hours window, measure/report over your market-hours time range (or apply a recording rule outside this repo).

### SLO 2 — Strategy evaluation continuity (market hours)

- **Objective**: **99%** of strategy cycles are **not skipped due to internal errors**.
- **Rationale**: skipping cycles silently is worse than failing loudly; this SLO keeps alerts aligned to reliability, not market outcomes.
- **Signals**:
  - `strategy_cycles_total`
  - `strategy_cycles_skipped_total`

**How to measure (PromQL example):**

```text
1 - (increase(strategy_cycles_skipped_total[1d]) / increase(strategy_cycles_total[1d]))
```

### SLO 3 — Ops endpoint availability (platform)

- **Objective**: **99.9%** of scrape intervals can reach `/ops/status` and `/metrics` for:
  - `marketdata-mcp-server`
  - `strategy-engine`
- **Rationale**: if ops endpoints are down, you lose observability during incidents.
- **Signal**: Prometheus `up` metric (via GMP) per target/job.

**How to measure (PromQL example):**

```text
avg_over_time(up[30d])
```

### Alert alignment

These SLOs map directly to:
- `Marketdata stale (warning)` → SLO 1 burn
- `Strategy engine halted/unhealthy (critical)` → SLO 2/SLO 3
- `CrashLoop / frequent restarts (critical)` → protects SLO 3 (and overall platform reliability)

