## Strategy cooldown (per-symbol)

This repo supports a **per-symbol cooldown** at the execution-risk layer to prevent rapid-fire re-trading (especially for **OPTIONS**) which can inflate slippage and drawdown.

### Configuration (environment variables)

- **`EXEC_OPTIONS_SYMBOL_COOLDOWN_ENABLED`**: `true|false` (default: `true`)
- **`EXEC_OPTIONS_SYMBOL_COOLDOWN_SECONDS`**: default cooldown in seconds (default: `600` = 10 minutes)
- **`EXEC_OPTIONS_SYMBOL_COOLDOWN_SIDES`**: which sides are gated, e.g. `buy` or `buy,sell` (default: `buy`)
- **`EXEC_OPTIONS_SYMBOL_COOLDOWN_OVERRIDES_JSON`**: per-symbol overrides in seconds (JSON map)

Example (5–15 minute per-symbol cooldowns):

```bash
export EXEC_OPTIONS_SYMBOL_COOLDOWN_ENABLED=true
export EXEC_OPTIONS_SYMBOL_COOLDOWN_SECONDS=600
export EXEC_OPTIONS_SYMBOL_COOLDOWN_SIDES="buy"
export EXEC_OPTIONS_SYMBOL_COOLDOWN_OVERRIDES_JSON='{"SPY":300,"AAPL":900}'
```

### Example block log

When a trade is blocked due to an active cooldown, execution emits a warning log:

```text
exec.cooldown_block {"check":"symbol_cooldown","enabled":true,"asset_class":"OPTIONS","symbol":"SPY240119C00450000","side":"buy","cooldown_seconds":600.0,"elapsed_seconds":12.3,"remaining_seconds":587.7,"tenant_id":null,"broker_account_id":"acct1"}
```

