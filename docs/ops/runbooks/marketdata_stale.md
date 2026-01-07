# Runbook: Marketdata stale (`/healthz` = 503)

## Safety posture

- Treat stale/unreachable marketdata as **hard-stop** for strategy execution and any execution pathways.
- Do **not** change `EXECUTION_HALTED` from automation.

## Symptoms

- `curl $MARKETDATA_HEALTH_URL` returns **503**
- Response shows `ok=false` or `age_seconds > max_age_seconds`
- Strategy logs show “Refusing to run: marketdata_stale”

## Likely causes

- Upstream broker feed outage / credentials invalid
- Marketdata streamer crash / crash loop
- Network/DNS issues between consumers and marketdata service
- Time skew / incorrect threshold (`MARKETDATA_MAX_AGE_SECONDS`)

## Immediate actions (safe)

1. **Capture artifacts**
   - Run `./scripts/ops_pre_market.sh` (or `./scripts/ops_post_market.sh`) and save the generated run directory.
2. **Verify service health locally**
   - `curl -i "$MARKETDATA_HEALTH_URL"`
   - If in k8s, also check pods and recent events.
3. **Inspect marketdata logs**
   - In k8s: `kubectl -n trading-floor logs deploy/marketdata-mcp-server --tail=200`
4. **Validate credentials wiring**
   - Confirm secrets are mounted and files exist (do not print secret contents).

## Verification (done when…)

- `GET /healthz` returns **200** with `ok=true`
- `age_seconds <= max_age_seconds`
- Strategy runtime resumes normal observe-only behavior (no repeated refusals)

