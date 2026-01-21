## AgentTrader v2 Domain Contracts — Versioning & Compatibility

### Canonical identity

Every contract object **MUST** include:

- `schema` (string): stable identifier (e.g., `agenttrader.v2.order_intent`)
- `schema_version` (SemVer string): current canonical version is `2.0.0`

### Required vs optional fields

- **Required** fields are those marked required in each JSON Schema’s `required` list.
- **Optional** fields are explicitly nullable or absent (including all `options` fields).

Contract-specific notes:

- **TradingSignal**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `signal_id`, `strategy_id`, `symbol`, `asset_class`, `action`, `generated_at`
  - **Optional**: `side`, `expires_at`, `confidence`, `strength`, `horizon`, `rationale`, `features`, `correlation_id`, `environment`, `meta`, `options`
- **OrderIntent**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `intent_id`, `account_id`, `symbol`, `asset_class`, `side`, `order_type`, `time_in_force`
  - **Optional**: `strategy_id`, `signal_id`, `quantity`, `notional`, `limit_price`, `stop_price`, `currency`, `client_intent_ref`, `constraints`, `correlation_id`, `environment`, `meta`, `options`
- **ShadowTrade**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `shadow_trade_id`, `symbol`, `asset_class`, `side`, `quantity`, `price`, `traded_at`
  - **Optional**: `strategy_id`, `intent_id`, `fees`, `notes`, `correlation_id`, `environment`, `meta`, `options`
- **RiskDecision**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `decision_id`, `evaluated_at`, `decision`, `allowed`, `reasons`
  - **Optional**: `intent_id`, `strategy_id`, `account_id`, `modification`, `correlation_id`, `environment`, `meta`, `options`
- **ExecutionAttempt**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `attempt_id`, `intent_id`, `attempt_number`, `requested_at`, `execution_mode`
  - **Optional**: `idempotency_key`, `correlation_id`, `environment`, `meta`, `options`
- **ExecutionResult**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `result_id`, `attempt_id`, `intent_id`, `recorded_at`, `status`
  - **Optional**: `filled_quantity`, `remaining_quantity`, `average_fill_price`, `fills`, `external_ids`, `error_code`, `error_message`, `correlation_id`, `environment`, `meta`, `options`
- **StrategyExplanation**
  - **Required**: `schema`, `schema_version`, `tenant_id`, `created_at`, `explanation_id`, `strategy_id`, `subject_type`, `subject_id`, `summary`
  - **Optional**: `narrative`, `key_factors`, `model_info`, `correlation_id`, `environment`, `meta`, `options`

### Backward compatibility rules

Consumers **MUST**:

- **Ignore unknown fields** (forward-compatible parsing).
- Treat missing optional fields as absent/`null`.
- Treat unknown enum values defensively (e.g., map to `other` / `unknown` behavior).

Producers **MUST NOT**:

- Add new required fields without a **MAJOR** version bump.
- Remove or rename fields without a **MAJOR** version bump.
- Change units/meaning of an existing field without a **MAJOR** version bump.

### SemVer policy for `schema_version`

- **MAJOR** (breaking): required field additions, removals/renames, meaning/unit changes, tightened validation.
- **MINOR** (non-breaking): add new **optional** fields; widen enums.
- **PATCH**: clarifying descriptions/examples only (no structural schema change).

### Broker-specific leakage policy

Core v2 contracts are **broker-agnostic**:

- No broker-specific identifiers/fields are modeled directly.
- When cross-system references are required, use generic `external_ids` maps (optional),
  without prescribing broker-specific keys in the core schema.

