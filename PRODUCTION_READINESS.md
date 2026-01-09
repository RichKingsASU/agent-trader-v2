# Production Readiness Checklist

## Runtime invariants

- [ ] All long-running services expose `/healthz` and `/ops/status` (or equivalent) and return non-200 on non-ready states.
- [ ] Readiness probes are configured for every long-running workload.
- [ ] Liveness probes are configured for every long-running workload.
- [ ] Startup probes are configured where cold start exceeds readiness thresholds.
- [ ] Graceful shutdown is implemented (SIGTERM/SIGINT handlers) and verified for every long-running loop.
- [ ] Shutdown gate prevents starting new broker submissions once shutdown is requested.
- [ ] In-flight broker submissions are drained (bounded timeout) on shutdown.
- [ ] Global kill switch (`EXECUTION_HALTED` / `EXECUTION_HALTED_FILE`) is wired into all broker-side execution boundaries.
- [ ] Kill switch is observable in runtime status surfaces (logs + `/ops/status`) across services.
- [ ] Default cluster posture is halted (`EXECUTION_HALTED=1`) until an explicit go-live action is taken.
- [ ] `EXEC_DRY_RUN` defaults to enabled and is required for non-production environments.
- [ ] Live execution is refused unless agent state machine is explicitly authorized (`AGENT_MODE=LIVE` + agent state `READY`).
- [ ] No workload is deployed with `AGENT_MODE=LIVE` / `EXECUTE` unless an explicit production go-live is in progress.
- [ ] No “bypass” toggles are enabled in production manifests (e.g., `MARKETDATA_HEALTH_CHECK_DISABLED`, `MARKETDATA_FORCE_STALE`).
- [ ] Marketdata service health check is enforced and blocks execution when stale/unhealthy.
- [ ] All images are pinned (no `:latest` tags) across `k8s/`, `infra/`, and build manifests.
- [ ] Kubernetes manifests surface immutable build fingerprints (`git_sha` and `BUILD_ID`).
- [ ] Deployed pods show image digests (`imageID` present) for every container.
- [ ] Execution workloads are disabled/scaled to 0 by default unless explicitly required and authorized for live trading.
- [ ] Services are `ClusterIP` by default (no unintended public exposure via `LoadBalancer`/`NodePort`).
- [ ] Capacity headroom is monitored (CPU/mem) and metrics are available (metrics-server/RBAC in place).
- [ ] Readiness gate script (`scripts/readiness_check.sh`) passes for the target namespace.
- [ ] Repo preflight scripts (if present) pass (e.g., `scripts/preflight.sh`).
- [ ] “Last Known Good” release tagging exists and is current (`v2-release-*` tags).
- [ ] Working tree is clean at build/release time (no uncommitted changes).
- [ ] Every service has bounded retries with backoff and jitter on external calls.
- [ ] Every retry loop has a maximum retry horizon or a circuit breaker to prevent infinite hot loops.
- [ ] All timestamps are UTC at boundaries and in persisted records.
- [ ] Clock skew assumptions are documented and validated (NTP/time sync present in runtime environment).
- [ ] Configuration is fully externalized (env/config) with safe defaults (fail-closed).
- [ ] Secrets are sourced from a secret manager (no plaintext secrets in env files committed to repo).
- [ ] Dependency lock strategy exists and builds are reproducible.
- [ ] Container builds run with minimal base images and non-root users where possible.
- [ ] Logging is structured and includes correlation IDs (request ID / intent ID / order ID).
- [ ] Alerting exists for: kill-switch active, breaker triggered, execution refused, marketdata unhealthy, and broker errors.

## Capital safety invariants

- [ ] Capital (cash) never goes negative under any path (including partial fills, retries, and failures).
- [ ] Equity/cash mark-to-market updates never produce negative values due to arithmetic/rounding issues.
- [ ] Every order intent is risk-validated prior to any broker submission.
- [ ] Risk validation is fail-closed by default (risk-data fetch failure blocks execution).
- [ ] Any “fail open” override exists only as an explicit, auditable, time-bounded operator action.
- [ ] Global kill switch blocks all broker submissions (defense in depth at the broker boundary).
- [ ] Per-account max daily trades is enforced (`EXEC_MAX_DAILY_TRADES`) and validated against the ledger.
- [ ] Per-symbol max position quantity is enforced (`EXEC_MAX_POSITION_QTY`) using projected post-trade position.
- [ ] Position-limit logic is symmetric for long and short exposure (absolute projected qty bounded).
- [ ] Order size validation prevents overspend/over-notional beyond available buying power/cash.
- [ ] No strategy can bypass execution risk controls (strict separation: strategy emits intents, execution routes).
- [ ] Dry-run mode never routes orders and is enforced centrally (not per-strategy).
- [ ] Client order IDs preserve intent→execution traceability (`client_order_id = client_intent_id`).
- [ ] Duplicate/replayed execute requests cannot create duplicate broker submissions (idempotent boundary).
- [ ] Circuit breaker: daily loss limit is enforced (e.g., -2% PnL threshold) and triggers safety action.
- [ ] Circuit breaker: daily loss action is “switch to SHADOW_MODE / halt new risk” (no further scaling into loss).
- [ ] Circuit breaker: VIX guard is enforced (high vol reduces allocation) and is observable/audited.
- [ ] Circuit breaker: concentration guard is enforced (>20% position concentration downgrades BUY to HOLD).
- [ ] Strategy safety breaker: missing market data forces a safe “flat / no-trade” decision.
- [ ] Strategy safety breaker: abnormal volatility (vol ratio) is configurable and disabled by default until tuned.
- [ ] Execution safety breaker: consecutive realized losses gate is configurable and disabled by default until tuned.
- [ ] Breaker evaluations are deterministic and produce audit artifacts (inputs, thresholds, decision).
- [ ] Breaker failures are safe: failure to evaluate does not permit unsafe execution without an explicit policy.
- [ ] All fees/commissions are accounted for in realized PnL computations used for breakers.
- [ ] PnL computations use consistent units and rounding (Decimal/money-safe arithmetic at boundaries).
- [ ] Max leverage / margin usage constraints are enforced where applicable (asset-class aware).
- [ ] No order is placed without explicit side/qty/symbol validation (no null/empty/NaN quantities).
- [ ] All quantities are normalized and validated (lot size, min increment, options contract multiplier where applicable).
- [ ] Order types are constrained to an allow-list (market/limit/etc.) appropriate to the broker and asset class.
- [ ] Slippage/price guards exist for limit orders and for illiquid instruments (operator-configurable).
- [ ] Cancel/replace behavior is bounded to prevent runaway churn (rate limits, max retries).
- [ ] Broker outage behavior is safe (no repeated submissions that can duplicate exposure).
- [ ] Manual intervention procedure exists to flatten/hedge positions if execution is halted mid-session.

## Event safety invariants

- [ ] All externally-ingested events are versioned and schema-validated at the boundary.
- [ ] Event processing is idempotent (safe under at-least-once delivery).
- [ ] Deduplication keys exist for every event type (order intent ID, broker order ID, ingestion event ID).
- [ ] Ledger writes are idempotent (upserts/merge semantics keyed by broker order ID).
- [ ] Partial fills update the same ledger record (no fill duplication across retries).
- [ ] Every event mutation is append-only or auditable (no silent overwrite without audit trail).
- [ ] All state transitions are explicit and validated (no “skip” transitions in agent/execution state machines).
- [ ] Event timestamps are recorded in UTC and include both event-time and ingest-time.
- [ ] Clock skew does not break ordering assumptions (ordering uses monotonic IDs or explicit sequence when required).
- [ ] Poison messages are quarantined (dead-letter queue / quarantine collection) with operator visibility.
- [ ] Retries have backoff and do not cause duplicate side effects (side effects behind idempotent gates).
- [ ] Exactly-once is not assumed; at-least-once is supported end-to-end.
- [ ] Fan-out publishing is bounded and failure-isolated (one subscriber failure doesn’t corrupt global state).
- [ ] Correlation IDs propagate across services (intent ID, run ID, strategy ID, tenant/user IDs).
- [ ] Events include minimal required identity fields (tenant/user/strategy/run) and are validated.
- [ ] PII/secret material is excluded from event payloads and logs by construction.
- [ ] Storage paths/collections are stable and documented (FireStore schema governance is enforced).
- [ ] Backfills and replays are safe: replaying historical events cannot place live orders.
- [ ] Shadow mode is enforced for replay/backtest contexts (cannot cross the live execution boundary).
- [ ] Event consumers can be paused safely (kill switch / shutdown) without losing auditability.
- [ ] Audit artifacts are generated for readiness and deployments (reports are stored and reviewable).
- [ ] Operational markers (heartbeats) exist to detect stuck loops and stalled pipelines.
- [ ] Alerting exists for event lag, DLQ growth, schema validation failures, and dedup anomalies.

## Agent platform invariants

- [ ] Strategies cannot directly call broker APIs (all broker actions go through the execution boundary).
- [ ] Execution is gated by an explicit agent mode/state machine (`AGENT_MODE` + `READY` required for live).
- [ ] Global kill switch is available to operators and works without restarts (ConfigMap-mounted file recommended).
- [ ] Kill switch drill is documented and practiced (enable/disable, expected logs, expected HTTP responses).
- [ ] Deployment defaults are safe (halted + dry-run) and require explicit operator action to go live.
- [ ] Zero-trust posture: least-privilege service accounts and narrowly scoped IAM permissions.
- [ ] Workload identity/ADC is used for cloud services (no long-lived JSON keys in production).
- [ ] Network exposure is minimized (internal services are not publicly reachable by default).
- [ ] Rate limits exist at ingress and at broker boundaries (prevent accidental request floods).
- [ ] Observability is complete: metrics, logs, traces (where supported) and dashboards exist for core SLOs.
- [ ] SLOs are defined for: marketdata freshness, execution latency, broker error rate, and event lag.
- [ ] On-call runbooks exist for: kill switch, strategy engine halted, broker outage, marketdata outage, and DR.
- [ ] Disaster recovery plan exists and is tested (restore from backups, redeploy from manifests, validate readiness).
- [ ] Backups exist for critical state (ledger, configs, strategy state) with retention and restore validation.
- [ ] Change control exists: LKG tagging, release notes, and rollback procedure (`scripts/restore_lkg.sh` or equivalent).
- [ ] Production builds are immutable and reproducible (pinned deps, pinned images, provenance recorded).
- [ ] No debug endpoints or admin bypass paths are enabled in production.
- [ ] Config changes are auditable (who/when/what) and use a controlled promotion process.
- [ ] Automated promotion checklist exists and is followed for strategy/config changes.
- [ ] Security scanning exists for container images and dependencies (and gates release when critical findings exist).
- [ ] Incident response includes postmortems and follow-up hardening items for safety controls.
